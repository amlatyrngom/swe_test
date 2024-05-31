## Setup
### Prereqs
NOTE: There might be other things that were implictly present in my system.
#### Ubuntu (untested for now)
```sh
sudo apt update
sudo apt install wget libopenblas-base libomp-dev default-jdk memcached libmemcached-tools
```

#### Mac
```sh
brew install wget libomp openblas openjdk libmemcached
```

#### Both
```sh
wget https://repo1.maven.org/maven2/io/anserini/anserini/0.36.1/anserini-0.36.1-fatjar.jar
mkdir anserini-jar
mv anserini-0.36.1-fatjar.jar anserini-jar
```

Now create a `.env` file with the following:
```sh
OPENAI_API_KEY=<key>
```

### SWE-Bench
```sh
git submodule update --init --recursive
pip install -r requirements.txt
pip install ./SWE-bench
```

### Sanity Check 1: Try inference and evaluation on lite oracle dataset with OpenAI

```sh
mkdir -p sanity-check
# Generate some inferences on 3 examples (3=300/100).
python SWE-bench/inference/run_api.py --dataset_name_or_path princeton-nlp/SWE-bench_Lite_oracle --model_name_or_path gpt-4-0613 --output_dir ./sanity-check --shard_id 0 --num_shards 100

# Check their accuracy. 1 out of the 3 examples should work correctly.
python SWE-bench/swebench/harness/run_evaluation.py --predictions_path "sanity-check/gpt-4-0613__SWE-bench_Lite_oracle__test__shard-0__num_shards-100.jsonl" --swe_bench_tasks "princeton-nlp/SWE-bench_Lite_oracle" --log_dir "sanity-check" --testbed "sanity-check" --skip_existing --timeout 900 --verbose
```

### Sanity Check 2: Try BM25 on lite oracle dataset.
```sh
mkdir -p sanity-check/data
ANSERINI_CLASSPATH=$PWD/anserini-jar python SWE-bench/inference/make_datasets/bm25_retrieval.py --dataset_name_or_path princeton-nlp/SWE-bench_Lite  --shard_id 0 --num_shards 100 --splits test --output_dir sanity-check

python SWE-bench/inference/make_datasets/create_text_dataset.py --dataset_name_or_path princeton-nlp/SWE-bench_Lite --splits test --retrieval_file sanity-check/princeton-nlp__SWE-bench_Lite/file_name_and_contents.retrieval.jsonl --file_source bm25 --output_dir sanity-check/data --shard_id 0 --num_shards 100
```

