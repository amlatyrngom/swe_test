llm_model=$1
echo "Cleaning up working_stage/evaluation/$llm_model"
rm -rf working_stage/evaluation/$llm_model/*.log
mkdir -p working_stage/evaluation/$llm_model
prediction_path="./working_stage/directone_code_only_fixes_${llm_model}_princeton-nlp__SWE-bench_Lite_dev.jsonl"
ls $prediction_path || exit 1
echo "Running evaluation for $llm_model. Predictions path: $prediction_path"

python SWE-bench/swebench/harness/run_evaluation.py\
    --predictions_path "$prediction_path"\
    --swe_bench_tasks "princeton-nlp/SWE-bench_Lite_oracle"\
    --log_dir "working_stage/evaluation"\
    --testbed "working_stage/evaluation"\
    --timeout "900"\
    --verbose
