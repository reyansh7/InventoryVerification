import os
import glob
import shutil

# Main project directories
MAIN_TRAIN_IMG = "train/images"
MAIN_TRAIN_LBL = "train/labels"
MAIN_VALID_IMG = "valid/images"
MAIN_VALID_LBL = "valid/labels"

BOXES_DIR = "new_dataset_boxes"
PALLETS_DIR = "new_dataset_pallets"

def ensure_dirs():
    for d in [MAIN_TRAIN_IMG, MAIN_TRAIN_LBL, MAIN_VALID_IMG, MAIN_VALID_LBL]:
        os.makedirs(d, exist_ok=True)

def process_boxes():
    print("--- Processing Boxes ---")
    kept = 0
    # Process both train and valid
    for split in ['train', 'valid']:
        lbl_dir = os.path.join(BOXES_DIR, split, 'labels')
        img_dir = os.path.join(BOXES_DIR, split, 'images')
        
        main_img = MAIN_TRAIN_IMG if split == 'train' else MAIN_VALID_IMG
        main_lbl = MAIN_TRAIN_LBL if split == 'train' else MAIN_VALID_LBL
        
        if not os.path.exists(lbl_dir):
            continue
            
        txt_files = glob.glob(os.path.join(lbl_dir, "*.txt"))
        for txt_file in txt_files:
            with open(txt_file, 'r') as f:
                lines = f.readlines()
                
            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if not parts: continue
                # In this dataset, all classes (0,1,2) are boxes. Map them to 0.
                parts[0] = "0"
                new_lines.append(" ".join(parts) + "\n")
                
            if len(new_lines) > 0:
                base_name = os.path.splitext(os.path.basename(txt_file))[0]
                new_base_name = f"box_{base_name}"
                
                # Write mapped label
                with open(os.path.join(main_lbl, new_base_name + ".txt"), 'w') as f:
                    f.writelines(new_lines)
                
                # Find and copy image
                for ext in ['.jpg', '.jpeg', '.png']:
                    img_path = os.path.join(img_dir, base_name + ext)
                    if os.path.exists(img_path):
                        shutil.copy(img_path, os.path.join(main_img, new_base_name + ext))
                        break
                kept += 1
    print(f"Processed and merged {kept} box images.")


def process_pallets():
    print("\n--- Processing Pallets ---")
    kept = 0
    discarded = 0
    # In new_dataset_pallets, Pallet is class 1.
    PALLET_CLASS_IN_DS = 1
    
    for split in ['train', 'valid']:
        lbl_dir = os.path.join(PALLETS_DIR, split, 'labels')
        img_dir = os.path.join(PALLETS_DIR, split, 'images')
        
        main_img = MAIN_TRAIN_IMG if split == 'train' else MAIN_VALID_IMG
        main_lbl = MAIN_TRAIN_LBL if split == 'train' else MAIN_VALID_LBL
        
        if not os.path.exists(lbl_dir):
            continue
            
        txt_files = glob.glob(os.path.join(lbl_dir, "*.txt"))
        for txt_file in txt_files:
            with open(txt_file, 'r') as f:
                lines = f.readlines()
                
            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if not parts: continue
                
                class_id = int(parts[0])
                if class_id == PALLET_CLASS_IN_DS:
                    # Keep it and map to our universal pallet ID (which is also 1, but we force it)
                    parts[0] = "1"
                    new_lines.append(" ".join(parts) + "\n")
                    
            if len(new_lines) == 0:
                discarded += 1
            else:
                base_name = os.path.splitext(os.path.basename(txt_file))[0]
                new_base_name = f"pallet_{base_name}"
                
                # Write mapped label
                with open(os.path.join(main_lbl, new_base_name + ".txt"), 'w') as f:
                    f.writelines(new_lines)
                
                # Find and copy image
                for ext in ['.jpg', '.jpeg', '.png']:
                    img_path = os.path.join(img_dir, base_name + ext)
                    if os.path.exists(img_path):
                        shutil.copy(img_path, os.path.join(main_img, new_base_name + ext))
                        break
                kept += 1
                
    print(f"Merged {kept} pure pallet images (discarded {discarded} useless images).")


if __name__ == "__main__":
    ensure_dirs()
    process_boxes()
    process_pallets()
    print("\n[SUCCESS] Datasets perfectly unified!")
