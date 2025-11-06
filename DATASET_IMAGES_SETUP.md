# SPIQA Dataset Images Setup Guide

## 📦 Image Files Location

The SPIQA dataset contains large image files (~424MB total) that are not stored directly in this repository:

- **Test-A Images**: `dataset/test-A/SPIQA_testA_Images/` (~119MB)
- **Test-B Images**: `dataset/test-B/SPIQA_testB_Images/` (~190MB)  
- **Test-C Images**: `dataset/test-C/SPIQA_testC_Images/` (~115MB)

## 🔄 Download Options

### Option 1: Official SPIQA Dataset (Recommended)

Download from the official source:

```bash
# Option 1a: Using Hugging Face Datasets
pip install datasets
python -c "from datasets import load_dataset; ds = load_dataset('google/spiqa'); ds.save_to_disk('./dataset/spiqa_raw')"
# Then extract images to corresponding directories

# Option 1b: Direct download from Hugging Face
# Visit: https://huggingface.co/datasets/google/spiqa
# Download test-A, test-B, test-C image archives
```

### Option 2: GitHub Releases (If Available)

If images are published as GitHub Releases:

```bash
# Download release assets
wget https://github.com/your-org/repo/releases/download/v1.0/SPIQA_testA_Images.zip
wget https://github.com/your-org/repo/releases/download/v1.0/SPIQA_testB_Images.zip
wget https://github.com/your-org/repo/releases/download/v1.0/SPIQA_testC_Images.zip

# Extract to dataset directories
unzip SPIQA_testA_Images.zip -d dataset/test-A/
unzip SPIQA_testB_Images.zip -d dataset/test-B/
unzip SPIQA_testC_Images.zip -d dataset/test-C/
```

### Option 3: Automated Download Script

A helper script is provided to download images:

```bash
python download_spiqa.py --images-only --test-sets A B C
```

## ✅ Verification

After downloading, verify images are in place:

```bash
# Check image counts
echo "Test-A: $(find dataset/test-A/SPIQA_testA_Images -name '*.png' | wc -l) images"
echo "Test-B: $(find dataset/test-B/SPIQA_testB_Images -name '*.png' | wc -l) images"
echo "Test-C: $(find dataset/test-C/SPIQA_testC_Images -name '*.png' | wc -l) images"
```

Expected counts:
- Test-A: ~2,252 images
- Test-B: ~794 images
- Test-C: ~2,243 images

## 📝 Note

The JSON metadata files (`SPIQA_testA.json`, `SPIQA_testB.json`, `SPIQA_testC.json`) are included in this repository. Only the image files need to be downloaded separately.

