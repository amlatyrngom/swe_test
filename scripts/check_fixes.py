import os
import argparse
import json

phrases = {
    "success": ["All tests passed"],
    "test_failure": ["Some tests failed"],
    "install_failure": ["Installation failed"],
    "patch_failure": ["Apply patch failed"],
    "test_script_failure": ["Test script run failed"],
}

def main(eval_path):
    results = {
        k: 0 for k in phrases.keys()
    }
    results["unknown"] = 0
    # Iterate through files in the eval_path ending with .eval.log
    files = [file for file in os.listdir(eval_path) if file.endswith(".eval.log")]
    files.sort()
    for file in files:
        # print(f"Checking {file}")
        with open(os.path.join(eval_path, file), "r") as f:
            content = f.read().lower()
            success = any(phrase.lower() in content for phrase in phrases["success"])
            if success:
                results["success"] += 1
            else:
                failure_type = None
                for k, v in phrases.items():
                    if any(phrase.lower() in content for phrase in v):
                        failure_type = k
                        print(f"File {file}: {failure_type}")
                        break
                if failure_type is not None:
                    results[failure_type] += 1
                else:
                    print(f"File {file}: Unknown")
                    results["unknown"] += 1
    print(json.dumps(results, indent=4))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval_path", required=True, type=str)
    args = parser.parse_args()
    main(**vars(args))