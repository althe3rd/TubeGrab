#!/bin/bash
# Quick script to check ID3 tags in audio files

if [ -z "$1" ]; then
    echo "Usage: $0 <audio_file>"
    echo "Example: $0 downloads/song.mp3"
    exit 1
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
    echo "Error: File not found: $FILE"
    exit 1
fi

echo "=== Metadata for: $FILE ==="
echo ""

# Use ffprobe to show metadata
ffprobe -v quiet -print_format json -show_format "$FILE" | python3 -c "
import json
import sys

data = json.load(sys.stdin)
format_info = data.get('format', {})
tags = format_info.get('tags', {})

if tags:
    print('ID3 Tags:')
    print('-' * 40)
    for key, value in tags.items():
        if key not in ['encoder', 'date']:
            print(f'{key.capitalize():20} : {value}')
    print('-' * 40)
else:
    print('⚠️  No metadata tags found!')
    print('This file was likely downloaded before metadata embedding was added.')
"

