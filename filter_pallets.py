import os
import yaml
import glob
import shutil

# This script will filter a new dataset to keep ONLY the pallets, 
# and re-map the class ID to '1' so it perfectly matches your original dataset!

NEW_DATASET_DIR = "new_dataset"  # Put your downloaded 8k dataset folder here!
TARGET_CLASS_NAME = "pallet"
OUR_PALLET_ID = 1  # In your original data.yaml, 'box' is 0, 'pallet' is 1.

def main():
    yaml_path = os.path.join(NEW_DATASET_DIR, "data.yaml")
    
    if not os.path.exists(yaml_path):
        print(f"Error: Could not find {yaml_path}. Did you extract the dataset to '{NEW_DATASET_DIR}'?")
        return

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    # Find the class ID of 'pallet' in the new dataset
    names = data.get('names', [])
    old_pallet_id = -1
    
    if isinstance(names, dict):
        # Some YOLO formats use dict {0: 'class1', 1: 'class2'}
        for k, v in names.items():
            if TARGET_CLASS_NAME.lower() in str(v).lower():
                old_pallet_id = k
                break
    elif isinstance(names, list):
        # Normal YOLO format ['class1', 'class2']
        for i, name in enumerate(names):
            if TARGET_CLASS_NAME.lower() in str(name).lower():
                old_pallet_id = i
                break

    if old_pallet_id == -1:
        print(f"Error: Could not find any class named '{TARGET_CLASS_NAME}' in the new dataset's data.yaml!")
        print(f"Available classes: {names}")
        return

    print(f"Found '{TARGET_CLASS_NAME}' at class ID {old_pallet_id} in the new dataset.")
    print("Scanning through labels and deleting non-pallet images...")

    deleted_count = 0
    kept_count = 0

    for split in ['train', 'valid', 'test']:
        lbl_dir = os.path.join(NEW_DATASET_DIR, split, 'labels')
        img_dir = os.path.join(NEW_DATASET_DIR, split, 'images')
        
        if not os.path.exists(lbl_dir):
            continue
            
        txt_files = glob.glob(os.path.join(lbl_dir, "*.txt"))
        
        for txt_file in txt_files:
            with open(txt_file, 'r') as f:
                lines = f.readlines()
            
            # Filter lines: only keep ones that match the old_pallet_id
            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if not parts: continue
                
                class_id = int(parts[0])
                if class_id == old_pallet_id:
                    # Rewrite the class ID to our system's pallet ID (1)
                    parts[0] = str(OUR_PALLET_ID)
                    new_lines.append(" ".join(parts) + "\n")
            
            base_name = os.path.splitext(os.path.basename(txt_file))[0]
            
            if len(new_lines) == 0:
                # No pallets in this image, delete the text file
                os.remove(txt_file)
                
                # Delete the corresponding image
                for ext in ['.jpg', '.jpeg', '.png']:
                    img_path = os.path.join(img_dir, base_name + ext)
                    if os.path.exists(img_path):
                        os.remove(img_path)
                deleted_count += 1
            else:
                # Pallet exists! Overwrite the text file with ONLY the pallet annotations
                with open(txt_file, 'w') as f:
                    f.writelines(new_lines)
                kept_count += 1

    print("\n--- DONE ---")
    print(f"Kept {kept_count} images containing perfectly mapped pallets.")
    print(f"Deleted {deleted_count} useless images.")
    print("\nYou can now safely copy the contents of new_dataset/train and new_dataset/valid directly into your main project folder!")

if __name__ == "__main__":
    main()
