import torch
from torch import optim
import numpy as np
import argparse
import time
import os
import random
from torch.utils.data import DataLoader
from data_provider.data_loader import Dataset_ETT_hour, Dataset_ETT_minute, Dataset_Custom, Dataset_PEMS
from model.TimeKD_recon_on import Dual
from utils.metrics import MSE, MAE, metric
import faulthandler
faulthandler.enable() 
torch.cuda.empty_cache()
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:150"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default="cuda:6", help="")
    parser.add_argument("--data_path", type=str, default="ETTh1", help="data path")
    parser.add_argument("--channel", type=int, default=512, help="number of features")
    parser.add_argument("--num_nodes", type=int, default=7, help="number of nodes")
    parser.add_argument("--seq_len", type=int, default=96, help="seq_len")
    parser.add_argument("--pred_len", type=int, default=96, help="out_len")
    parser.add_argument("--batch_size", type=int, default=32, help="batch size")
    parser.add_argument("--lrate", type=float, default=1e-4, help="learning rate")
    parser.add_argument("--dropout_n", type=float, default=0.2, help="dropout rate of neural network layers")
    parser.add_argument("--d_llm", type=int, default=768, help="hidden dimensions")
    parser.add_argument("--l_layer", type=int, default=1, help="layers of llm")
    parser.add_argument("--e_layer", type=int, default=1, help="layers of transformer encoder")
    parser.add_argument("--head", type=int, default=8, help="heads of attention")
    parser.add_argument("--model_name", type=str, default="gpt2", help="llm")
    parser.add_argument("--weight_decay", type=float, default=1e-3, help="weight decay rate")
    parser.add_argument('--num_workers', type=int, default=10, help='data loader num workers')
    parser.add_argument("--epochs", type=int, default=100, help="")
    parser.add_argument('--seed', type=int, default=2036, help='random seed')
    parser.add_argument(
        "--es_patience",
        type=int,
        default=50,
        help="quit if no improvement after this many iterations",
    )
    parser.add_argument(
        "--save",
        type=str,
        default="./logs/" + str(time.strftime("%Y-%m-%d-%H:%M:%S")) + "-",
        help="save path",
    )
    return parser.parse_args()

class trainer:
    def __init__(
        self,
        scaler,
        data_path,
        channel,
        num_nodes,
        seq_len,
        pred_len,
        dropout_n,
        d_llm,
        l_layer,
        e_layer,
        head,
        lrate,
        wdecay,
        device,
        epochs
    ):
        self.model = Dual(
            device=device, data_path=data_path, channel=channel, num_nodes=num_nodes, seq_len=seq_len, pred_len=pred_len, 
            dropout_n=dropout_n, d_llm=d_llm, l_layer=l_layer, e_layer=e_layer, head=head
        )
        
        self.optimizer = optim.AdamW(self.model.parameters(), lr=lrate, weight_decay=wdecay)
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=epochs, eta_min=1e-6)
        self.loss = MSE
        self.MAE = MAE
        self.clip = 5
        self.scaler = scaler
        self.device = device
        print("The number of trainable parameters: {}".format(self.model.count_trainable_params()))
        print("The number of parameters: {}".format(self.model.param_num()))
        print(self.model)

    def train(self, x, y, x_mark, y_mark):
        self.model.train()
        self.optimizer.zero_grad()
        predict= self.model(x, y, x_mark, y_mark)
        loss = self.loss(predict, y)
        loss.backward()
        if self.clip is not None:
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.clip)
        self.optimizer.step()
        mae = self.MAE(predict, y)
        return loss.item(), mae.item()
    
    def eval(self, x, y, x_mark, y_mark):
        self.model.eval()
        with torch.no_grad():
            predict = self.model(x, y, x_mark, y_mark)
            loss = self.loss(predict, y)
            mae = self.MAE(predict, y)
        return loss.item(), mae.item()


def load_data(args):
    data_map = {
        'ETTh1': Dataset_ETT_hour,
        'ETTh2': Dataset_ETT_hour,
        'ETTm1': Dataset_ETT_minute,
        'ETTm2': Dataset_ETT_minute,
        'PEMS08S': Dataset_PEMS
    }
    data_class = data_map.get(args.data_path, Dataset_Custom)
    train_set = data_class(flag='train', scale=True, size=[args.seq_len, 0, args.pred_len], data_path=args.data_path)
    val_set = data_class(flag='val', scale=True, size=[args.seq_len, 0, args.pred_len], data_path=args.data_path)
    test_set = data_class(flag='test', scale=True, size=[args.seq_len, 0, args.pred_len], data_path=args.data_path)
    
    scaler = train_set.scaler

    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=False, drop_last=True, num_workers=args.num_workers)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False, drop_last=True, num_workers=args.num_workers)
    test_loader = DataLoader(test_set, batch_size=1, shuffle=False, drop_last=False, num_workers=args.num_workers)

    return train_loader, val_loader, test_loader, scaler

def seed_it(seed):
    random.seed(seed)
    os.environ["PYTHONSEED"] = str(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.enabled = True
    torch.manual_seed(seed)

def main():
    args = parse_args()
    train_loader, val_loader, test_loader,scaler = load_data(args)
    seed_it(args.seed)
    device = torch.device(args.device)
    
    loss = 9999999
    test_log = 999999
    epochs_since_best_mse = 0

    path = os.path.join(args.save, args.data_path, 
                        f"{args.pred_len}_{args.channel}_{args.e_layer}_{args.lrate}_{args.dropout_n}_{args.seed}/")
    if not os.path.exists(path):
        os.makedirs(path)
     
    his_loss = []
    val_time = []
    train_time = []
    print(args)

    engine = trainer(
        scaler=scaler,
        data_path=args.data_path,
        channel=args.channel,
        num_nodes=args.num_nodes,
        seq_len=args.seq_len,
        pred_len=args.pred_len,
        dropout_n=args.dropout_n,
        d_llm=args.d_llm,
        l_layer=args.l_layer,
        e_layer=args.e_layer,
        head=args.head,
        lrate=args.lrate,
        wdecay=args.weight_decay,
        device=device,
        epochs=args.epochs
    )

    print("Start training...", flush=True)

    for i in range(1, args.epochs + 1):
        t1 = time.time()
        train_loss = []
        train_mae = []
        
        for iter, (x, y, x_mark, y_mark) in enumerate(train_loader):
            trainx = torch.Tensor(x).to(device)
            trainx_mark = torch.Tensor(x_mark).to(device)
            trainy = torch.Tensor(y).to(device)
            trainy_mark = torch.Tensor(y_mark).to(device)
            metrics = engine.train(trainx, trainy, trainx_mark, trainy_mark)
            train_loss.append(metrics[0])
            train_mae.append(metrics[1])

        t2 = time.time()
        log = "Epoch: {:03d}, Training Time: {:.4f} secs"
        print(log.format(i, (t2 - t1)))
        train_time.append(t2 - t1)

        # Validation
        val_loss = []
        val_mae = []
        s1 = time.time()

        for iter, (x, y, x_mark, y_mark) in enumerate(val_loader):
            valx = torch.Tensor(x).to(device)
            valx_mark = torch.Tensor(x_mark).to(device)
            valy = torch.Tensor(y).to(device)
            valy_mark = torch.Tensor(y_mark).to(device)
            metrics = engine.eval(valx, valy, valx_mark, valy_mark)
            val_loss.append(metrics[0])
            val_mae.append(metrics[1])

        s2 = time.time()
        log = "Epoch: {:03d}, Inference Time: {:.4f} secs"
        print(log.format(i, (s2 - s1)))
        val_time.append(s2 - s1)

        mtrain_loss = np.mean(train_loss)
        mtrain_mae = np.mean(train_mae)
        mvalid_loss = np.mean(val_loss)
        mvalid_mae = np.mean(val_mae)

        his_loss.append(mvalid_loss)
        print("-----------------------")

        log = "Epoch: {:03d}, Train Loss: {:.4f}, Train MAE: {:.4f} "
        print(
            log.format(i, mtrain_loss, mtrain_mae),
            flush=True,
        )
        log = "Epoch: {:03d}, Valid Loss: {:.4f}, Valid MAE: {:.4f}"
        print(
            log.format(i, mvalid_loss, mvalid_mae),
            flush=True,
        )

        if mvalid_loss < loss:
            print("###Update tasks appear###")
            if i <= 10:
                # It is not necessary to print the results of the testset when epoch is less than n, because the model has not yet converged.
                loss = mvalid_loss
                torch.save(engine.model.state_dict(), path + "best_model.pth")
                bestid = i
                epochs_since_best_mse = 0
                print("Updating! Valid Loss:{:.4f}".format(mvalid_loss), end=", ")
                print("epoch: ", i)
            else:
                test_outputs = []
                test_y = []

                for iter, (x, y, x_mark, y_mark) in enumerate(test_loader):
                    testx = torch.Tensor(x).to(device)
                    testx_mark = torch.Tensor(x_mark).to(device)
                    testy = torch.Tensor(y).to(device)
                    testy_mark = torch.Tensor(y_mark).to(device)
                    with torch.no_grad():
                        preds = engine.model(testx, testy, testx_mark, testy_mark)
                    test_outputs.append(preds)
                    test_y.append(testy)
                
                test_pre = torch.cat(test_outputs, dim=0)
                test_real = torch.cat(test_y, dim=0)

                amse = []
                amae = []
                
                for j in range(args.pred_len):
                    pred = test_pre[:, j,].to(device)
                    real = test_real[:, j, ].to(device)
                    metrics = metric(pred, real)
                    # log = "Evaluate best model on test data for horizon {:d}, Test MSE: {:.4f}, Test MAE: {:.4f}"
                    amse.append(metrics[0])
                    amae.append(metrics[1])

                # log = "On average horizons, Test MSE: {:.4f}, Test MAE: {:.4f}"
                # print(
                #     log.format(
                #         np.mean(amse), np.mean(amae)
                #     )
                # )

                if np.mean(amse) < test_log:
                    test_log = np.mean(amse)
                    loss = mvalid_loss
                    torch.save(engine.model.state_dict(), path + "best_model.pth")
                    epochs_since_best_mse = 0
                    print("Test low! Updating! Test MSE: {:.4f}, Test MAE: {:.4f}".format(np.mean(amse), np.mean(amae)), end=", ")
                    print("Test low! Updating! Valid Loss: {:.4f}".format(mvalid_loss), end=", ")

                    bestid = i
                    print("epoch: ", i)
                else:
                    epochs_since_best_mse += 1
                    print("No update")

        else:
            epochs_since_best_mse += 1
            print("No update")

        engine.scheduler.step()

        if epochs_since_best_mse >= args.es_patience and i >= args.epochs//2: # early stop
            break

    # Output consumption
    print("Average Training Time: {:.4f} secs/epoch".format(np.mean(train_time)))
    print("Average Inference Time: {:.4f} secs".format(np.mean(val_time)))

    # Test
    print("Training ends")
    print("The epoch of the best result：", bestid)
    print("The valid loss of the best model", str(round(his_loss[bestid - 1], 4)))
   
    engine.model.load_state_dict(torch.load(path + "best_model.pth"))
    
    test_outputs = []
    test_y = []

    for iter, (x, y, x_mark, y_mark) in enumerate(test_loader):
        testx = torch.Tensor(x).to(device)
        testx_mark = torch.Tensor(x_mark).to(device)
        testy = torch.Tensor(y).to(device)
        testy_mark = torch.Tensor(y_mark).to(device)
        with torch.no_grad():
            preds = engine.model(testx, testy, testx_mark, testy_mark)
        test_outputs.append(preds)
        test_y.append(testy)

        # if iter == 0:
        #     engine.model.plot_tsne(enc_out)
        #     engine.model.plot_attention_maps(att)

    test_pre = torch.cat(test_outputs, dim=0)
    test_real = torch.cat(test_y, dim=0)

    amse = []
    amae = []
    
    for j in range(args.pred_len):
        pred = test_pre[:, j,].to(device)
        real = test_real[:, j, ].to(device)
        metrics = metric(pred, real)
        # log = "Evaluate best model on test data for horizon {:d}, Test MSE: {:.4f}, Test MAE: {:.4f}"
        amse.append(metrics[0])
        amae.append(metrics[1])

    log = "On average horizons, Test MSE: {:.4f}, Test MAE: {:.4f}"
    print(log.format(np.mean(amse), np.mean(amae)))

if __name__ == "__main__":
    t1 = time.time()
    main()
    t2 = time.time()
    print("Total time spent: {:.4f}".format(t2 - t1))