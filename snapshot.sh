#!/bin/bash
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="backups/$TIMESTAMP"
mkdir -p "$BACKUP_DIR"
cp app.py logic.py "$BACKUP_DIR/" 2>/dev/null || cp app.py "$BACKUP_DIR/"
echo "Snapshot created at $BACKUP_DIR"

# Cleanup: Keep only last 50 backups
# Use ls -dt to sort by time (newest first), tail -n +51 to get the 51st and older
if [ -d "backups" ]; then
    ls -dt backups/*/ 2>/dev/null | tail -n +51 | xargs -I {} rm -rf "{}"
fi
