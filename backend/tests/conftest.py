import os
import tempfile
from pathlib import Path

# Point the store away from the real database, and make sure tests never call
# a real LLM even if .env contains a key.
TEST_ROOT = Path(tempfile.mkdtemp(prefix="finance_sim_test_"))
os.environ["DATABASE_PATH"] = str(TEST_ROOT / "test.db")
os.environ["RUNS_DIR"] = str(TEST_ROOT / "runs")
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["LLM_MODEL"] = "test-model"
