#!/bin/bash
# Remove tracked image files from git (but keep local files)
# This removes them from git tracking, but files remain on disk

set -e

echo "🗑️  Removing tracked image files from git..."
echo "================================================"

# Remove dataset image directories from git tracking
echo ""
echo "1. Removing dataset image directories from git..."
git rm -r --cached dataset/test-A/SPIQA_testA_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-B/SPIQA_testB_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-C/SPIQA_testC_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"

# Remove nested image directories
echo ""
echo "2. Removing nested image directories..."
git rm -r --cached dataset/test-A/test-A/SPIQA_testA_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-B/test-B/SPIQA_testB_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-C/test-C/SPIQA_testC_Images/ 2>/dev/null || echo "   (Already removed or doesn't exist)"

# Remove zip files
echo ""
echo "3. Removing zip files..."
git rm --cached dataset/test-A/test-A/SPIQA_testA_Images.zip 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm --cached dataset/test-B/test-B/SPIQA_testB_Images.zip 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm --cached dataset/test-C/test-C/SPIQA_testC_Images.zip 2>/dev/null || echo "   (Already removed or doesn't exist)"

# Remove extracted directories
echo ""
echo "4. Removing extracted directories..."
git rm -r --cached dataset/test-A/test-A/SPIQA_testA_Images.zip_extracted/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-B/test-B/SPIQA_testB_Images.zip_extracted/ 2>/dev/null || echo "   (Already removed or doesn't exist)"
git rm -r --cached dataset/test-C/test-C/SPIQA_testC_Images.zip_extracted/ 2>/dev/null || echo "   (Already removed or doesn't exist)"

# Remove old asset images (if they were deleted)
echo ""
echo "5. Removing deleted asset images from git..."
git rm --cached assets/logo.png 2>/dev/null || echo "   (Already removed)"
git rm --cached assets/rag_anything_framework.png 2>/dev/null || echo "   (Already removed)"

echo ""
echo "================================================"
echo "✅ Image files removed from git tracking!"
echo ""
echo "📋 Summary:"
echo "   - Dataset image directories removed from git"
echo "   - Zip files removed from git"
echo "   - Files remain on local disk (not deleted)"
echo ""
echo "⚠️  Note: These changes will be committed when you run 'git commit'"
echo "   The .gitignore will prevent them from being tracked again."

