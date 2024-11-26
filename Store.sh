 #!/bin/bash
export PYTHONPATH=/path/to/project_root:$PYTHONPATH
export CUDA_LAUNCH_BLOCKING=1

data_paths=("ETTm1" "ETTm2" "ETTh1" "ETTh2")
divides=("train" "val") 
device="cuda:7"
num_nodes=7
input_len=96
output_len_values=(24 36 48 96 192)
model_name=("gpt2")
d_model=768
l_layer=12

for data_path in "${data_paths[@]}"; do
  for divide in "${divides[@]}"; do
    for output_len in "${output_len_values[@]}"; do
      log_file="${data_path}_${output_len}_${divide}.log"
      nohup python store_emb.py \
        --data_path $data_path \
        --divide $divide \
        --device $device \
        --num_nodes $num_nodes \
        --input_len $input_len \
        --output_len $output_len \
        --model_name $model_name \
        --d_model $d_model \
        --l_layer $l_layer > $log_file &
    done
  done
done