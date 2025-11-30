#!/bin/bash
echo "Available backups:"
if [ -d "backups" ]; then
    ls -d backups/*/ | sort
else
    echo "No backups found."
    exit 1
fi
echo ""
read -p "Enter timestamp to restore (copy from above, e.g. 20251130_130000): " TIMESTAMP_INPUT

# Handle full path or just timestamp
TIMESTAMP=$(basename "$TIMESTAMP_INPUT")

if [ ! -d "backups/$TIMESTAMP" ]; then
    echo "Backup backups/$TIMESTAMP not found!"
    exit 1
fi

echo "Restore mode:"
echo "1) All (app.py + logic.py)"
echo "2) UI only (app.py)"
echo "3) Logic only (logic.py)"
read -p "Select (1/2/3): " MODE

case $MODE in
    1)
        [ -f "backups/$TIMESTAMP/app.py" ] && cp "backups/$TIMESTAMP/app.py" .
        [ -f "backups/$TIMESTAMP/logic.py" ] && cp "backups/$TIMESTAMP/logic.py" .
        echo "Restored All."
        ;;
    2)
        [ -f "backups/$TIMESTAMP/app.py" ] && cp "backups/$TIMESTAMP/app.py" .
        echo "Restored UI only."
        ;;
    3)
        [ -f "backups/$TIMESTAMP/logic.py" ] && cp "backups/$TIMESTAMP/logic.py" .
        echo "Restored Logic only."
        ;;
    *)
        echo "Invalid selection."
        exit 1
        ;;
esac
