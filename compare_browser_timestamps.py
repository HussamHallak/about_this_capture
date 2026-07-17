import sys
import os

def compare_files(file1_path, file2_path):
    """
    Compares two text files and finds lines unique to each file.
    Ignores case and leading/trailing whitespace during comparison.
    """
    # Check if files exist to provide a clean error message
    if not os.path.exists(file1_path):
        print(f"Error: File not found - {file1_path}")
        return
    if not os.path.exists(file2_path):
        print(f"Error: File not found - {file2_path}")
        return

    try:
        # Read lines from the first file
        # .strip() removes leading/trailing whitespace, .lower() makes it case-insensitive
        with open(file1_path, 'r', encoding='utf-8') as f1:
            lines1 = set(line.strip().lower() for line in f1)
            
        # Read lines from the second file
        with open(file2_path, 'r', encoding='utf-8') as f2:
            lines2 = set(line.strip().lower() for line in f2)
            
        # Calculate the differences using set operations
        only_in_file1 = lines1 - lines2
        only_in_file2 = lines2 - lines1
        
        # Print the results
        print(f"--- Comparison Results ---")
        print(f"Total unique lines in '{os.path.basename(file1_path)}': {len(lines1)}")
        print(f"Total unique lines in '{os.path.basename(file2_path)}': {len(lines2)}\n")

        if only_in_file1:
            print(f"[!] Lines ONLY in '{os.path.basename(file1_path)}' ({len(only_in_file1)} lines):")
            for line in only_in_file1:
                print(f"  - {line}")
        else:
            print(f"[i] No unique lines found in '{os.path.basename(file1_path)}'.")
            
        print("-" * 30)
        
        if only_in_file2:
            print(f"[!] Lines ONLY in '{os.path.basename(file2_path)}' ({len(only_in_file2)} lines):")
            for line in only_in_file2:
                print(f"  - {line}")
        else:
            print(f"[i] No unique lines found in '{os.path.basename(file2_path)}'.")

    except Exception as e:
        print(f"An error occurred while reading the files: {e}")

if __name__ == "__main__":
    if len(sys.argv) == 3:
        file_a = sys.argv[1]
        file_b = sys.argv[2]
    else:
        # Default fallback files for testing
        file_a = "file1.txt"
        file_b = "file2.txt"
        print(f"Usage: python {sys.argv[0]} <file1> <file2>")
        print(f"Running with default files: {file_a} and {file_b}\n")

    compare_files(file_a, file_b)