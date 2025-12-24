# PWA Icons

This directory should contain the following PNG icon files for Progressive Web App (PWA) support:

## Required Icons

- **icon-192.png** - 192x192 pixels (for Android and general PWA use)
- **icon-512.png** - 512x512 pixels (for Android and general PWA use)
- **apple-touch-icon.png** - 180x180 pixels (for iOS home screen)

## How to Create Icons

1. Use the `icon.svg` file as a source
2. Convert to PNG at the required sizes using:
   - Online tools: https://convertio.co/svg-png/
   - ImageMagick: `convert -background none -resize SIZE frontend/icon.svg frontend/icon-SIZE.png`
   - Or any image editor that supports SVG to PNG conversion

3. Place all three PNG files in the `frontend/` directory

## Notes

- Icons should have transparent backgrounds
- The SVG source (`icon.svg`) is already included and will be used as a fallback
- If PNG icons are missing, the app will still work but may not display properly when installed as a PWA

