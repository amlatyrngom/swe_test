llm_model=$1
prediction_path="./working_stage/direct_fixes.jsonl"
ls $prediction_path || exit 1
echo "Cleaning up working_stage/evaluation/$llm_model"
rm -rf working_stage/evaluation/$llm_model/*.log
mkdir -p working_stage/evaluation/$llm_model
echo "Running evaluation for $llm_model. Predictions path: $prediction_path"

python SWE-bench/swebench/harness/run_evaluation.py\
    --predictions_path "$prediction_path"\
    --swe_bench_tasks "princeton-nlp/SWE-bench_Lite_oracle"\
    --log_dir "working_stage/evaluation"\
    --testbed "working_stage/evaluation"\
    --timeout "900"\
    --verbose
