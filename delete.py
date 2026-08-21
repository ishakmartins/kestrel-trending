#!/usr/bin/env python3
"""
Delete all PNG and HTML files from run folders in the trends directory.
Removes files from _to_delete subfolders and cleans up the empty folders.
"""

import os
import shutil
from pathlib import Path

def delete_files():
    # Set the base path
    base_path = r"C:\githubrepo\kestrel-trending\dataset\trends"

    if not os.path.exists(base_path):
        print(f"❌ Error: Path does not exist: {base_path}")
        return

    deleted_count = 0
    folder_count = 0
    error_count = 0

    print(f"Starting cleanup of {base_path}...\n")

    # Iterate through all run_* folders
    for run_dir in sorted(os.listdir(base_path)):
        if not run_dir.startswith('run_'):
            continue

        run_path = os.path.join(base_path, run_dir)
        if not os.path.isdir(run_path):
            continue

        delete_folder = os.path.join(run_path, '_to_delete')

        # Check if _to_delete folder exists
        if os.path.isdir(delete_folder):
            try:
                # Delete all files in _to_delete folder
                for file in os.listdir(delete_folder):
                    file_path = os.path.join(delete_folder, file)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            deleted_count += 1
                    except Exception as e:
                        print(f"   ⚠️  Error deleting {file}: {e}")
                        error_count += 1

                # Remove the empty _to_delete folder
                try:
                    os.rmdir(delete_folder)
                    folder_count += 1
                    print(f"✓ {run_dir}: cleaned")
                except Exception as e:
                    print(f"⚠️  {run_dir}: folder not empty or error: {e}")
            except Exception as e:
                print(f"❌ Error processing {run_dir}: {e}")
                error_count += 1

    # Print summary
    print(f"\n{'='*60}")
    print(f"✓ Cleanup Complete!")
    print(f"{'='*60}")
    print(f"Files deleted:        {deleted_count}")
    print(f"Folders removed:      {folder_count}")
    print(f"Errors encountered:   {error_count}")
    print(f"{'='*60}")

if __name__ == "__main__":
    delete_files()
    input("\nPress Enter to exit...")