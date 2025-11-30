#!/bin/bash

# Auto Git Push Script for Gemini 3 Project
# This script automatically commits and pushes changes every 5 minutes

# Project directory
PROJECT_DIR="/Volumes/14TB/Python file/git用/gemini3proj"

# Log file
LOG_FILE="$PROJECT_DIR/auto_git_push.log"

# Timestamp
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# Change to project directory
cd "$PROJECT_DIR" || exit 1

# Function to log messages
log_message() {
    echo "[$TIMESTAMP] $1" >> "$LOG_FILE"
}

log_message "=== Auto Git Push Started ==="

# Check if there are any changes
if [[ -z $(git status --porcelain) ]]; then
    log_message "No changes to commit."
    exit 0
fi

# Add all changes
git add . >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    log_message "ERROR: git add failed"
    exit 1
fi

# Commit with timestamp
git commit -m "Auto-save: $TIMESTAMP" >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    log_message "ERROR: git commit failed"
    exit 1
fi

# Push to remote
git push >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    log_message "ERROR: git push failed"
    exit 1
fi

log_message "✓ Successfully pushed changes to GitHub"
log_message "=== Auto Git Push Completed ==="
