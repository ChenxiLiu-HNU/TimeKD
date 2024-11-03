#!/bin/bash
export PYTHONPATH="/data/cxliu/code/NeurIPS2023-One-Fits-All/Long-term_Forecasting/ST_LLM/TimeCMA/TimeKD:$PYTHONPATH"

seq_lens=(96)
pred_lens=(96)
learning_rates=(1e-5 1e-4)
channels=(256 768)
d_llm=(768)
e_layers=(6)
dropout_ns=(0.1 0.5)
batch_sizes=(16)

model_name="gpt2"
data_path="ETTh2"
epochs=(300)

for seq_len in "${seq_lens[@]}"; do 
  for pred_len in "${pred_lens[@]}"; do
    for learning_rate in "${learning_rates[@]}"; do
      for channel in "${channels[@]}"; do
        for dropout_n in "${dropout_ns[@]}"; do
          for e_layer in "${e_layers[@]}"; do
            for batch_size in "${batch_sizes[@]}"; do
              log_path="./Results/Recon/${data_path}/HD_GT/Off/"
              mkdir -p $log_path
              log_file="${log_path}i${seq_len}_o${pred_len}_lr${learning_rate}_c${channel}_el${e_layer}_dn${dropout_n}_bs${batch_size}_e${epochs}_ll16.log"
              nohup python train_recon_off.py \
                --data_path $data_path \
                --device cuda:6 \
                --batch_size $batch_size \
                --num_nodes 7 \
                --seq_len $seq_len \
                --pred_len $pred_len \
                --epochs $epochs \
                --seed 6666 \
                --channel $channel \
                --head 4 \
                --lrate $learning_rate \
                --dropout_n $dropout_n \
                --e_layer $e_layer \
                --model_name $model_name \
                --num_workers 10 \
                --d_llm $d_llm > $log_file &
            done
          done
        done
      done
    done
  done
done