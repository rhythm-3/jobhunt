#!/usr/bin/env python3
"""Load a CandidateProfile JSON file into the app's database: python3 scripts/load_profile.py profile.json"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jobagent.config import Settings
from jobagent.db import Store
from jobagent.schemas import CandidateProfile

p = CandidateProfile.model_validate_json(Path(sys.argv[1]).read_text())
Store(Settings().db_path).kv_set("profile", p.model_dump_json())
print(f"loaded profile for {p.full_name}: {len(p.skills)} skills, {len(p.experience)} roles, {len(p.projects)} projects")
