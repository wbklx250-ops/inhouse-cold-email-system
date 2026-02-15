#!/bin/bash
set -o pipefail

echo "=========================================="
echo " Cold Email Platform - Starting Up"
echo "=========================================="
echo ""

run_migrations() {
    echo "[MIGRATIONS] Attempting database migrations..."
    output=$(alembic upgrade head 2>&1)
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo "[MIGRATIONS] ✓ Migrations applied successfully"
        return 0
    fi
    
    if echo "$output" | grep -qi "multiple head"; then
        echo "[MIGRATIONS] Multiple heads detected - attempting auto-merge..."
        merge_output=$(alembic merge heads -m "auto_merge" 2>&1)
        if [ $? -eq 0 ]; then
            echo "[MIGRATIONS] Heads merged, retrying upgrade..."
            output=$(alembic upgrade head 2>&1)
            if [ $? -eq 0 ]; then
                echo "[MIGRATIONS] ✓ Migrations applied after merge"
                return 0
            fi
        fi
        echo "[MIGRATIONS] ✗ Auto-merge failed: $merge_output"
    fi
    
    if echo "$output" | grep -qiE "connection refused|timeout|could not connect|connection reset"; then
        echo "[MIGRATIONS] Database connection issue - waiting 5s and retrying..."
        sleep 5
        output=$(alembic upgrade head 2>&1)
        if [ $? -eq 0 ]; then
            echo "[MIGRATIONS] ✓ Migrations applied on retry"
            return 0
        fi
    fi
    
    echo "[MIGRATIONS] ✗ Migration failed (server will start anyway):"
    echo "$output" | head -20
    echo ""
    echo "[MIGRATIONS] ⚠ Check logs and run migrations manually if needed"
    return 1
}

run_migrations || true

echo ""
echo "=========================================="
echo " Starting Uvicorn Server"
echo "=========================================="
echo ""

exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
