"""Demo data so the dashboard is usable offline. Replace SAMPLE_PROFILE via POST /api/profile."""

SAMPLE_PROFILE = {
    "full_name": "Alex Morgan", "email": "alex@example.com", "phone": "+1 555 0100", "location": "Remote (US)",
    "summary": "Backend engineer with 6 years building Python services, data pipelines and LLM-powered tooling",
    "skills": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "AWS", "Kafka", "LLM", "SQL", "Terraform"],
    "experience": [
        {"company": "Northwind", "title": "Senior Backend Engineer", "start": "2022", "end": "present",
         "bullets": ["Designed FastAPI microservices on AWS handling 4k requests per second",
                     "Built Kafka event pipeline feeding PostgreSQL and Redis caches",
                     "Shipped LLM summarisation features with evaluation harness and cost tracking",
                     "Mentored four engineers and led the Terraform migration"]},
        {"company": "Contoso", "title": "Software Engineer", "start": "2019", "end": "2022",
         "bullets": ["Wrote Python ETL jobs processing 2TB daily into SQL warehouses",
                     "Containerised services with Docker and cut deploy time by half"]}],
    "education": ["B.S. Computer Science, State University"],
    "preferences": {"remote_only": False, "target_titles": ["engineer", "developer"],
                    "exclude_keywords": ["clearance required", "unpaid"]},
}

SAMPLE_JOBS = [
    {"id": "fx-1", "source": "fixtures", "url": "https://example.com/jobs/1", "title": "Senior Backend Engineer",
     "company": "Acme Cloud", "location": "Remote", "remote": True, "apply_email": "jobs@acme.example",
     "description": "Requirements\nPython and FastAPI experience\nPostgreSQL and Redis\nKafka event streaming\nAWS and Docker\n"
                    "Nice to have\nTerraform\nLLM tooling"},
    {"id": "fx-2", "source": "fixtures", "url": "https://example.com/jobs/2", "title": "ML Platform Engineer",
     "company": "Globex", "location": "NYC", "remote": False,
     "description": "Requirements\nPython, PyTorch and Kubernetes\nAirflow and Spark pipelines\nAWS\nNice to have\nRust"},
    {"id": "fx-3", "source": "fixtures", "url": "https://example.com/jobs/3", "title": "Frontend Developer",
     "company": "Initech", "location": "Remote", "remote": True,
     "description": "Requirements\nReact and TypeScript\nGraphQL\nCSS expertise\nNice to have\nNode"},
    {"id": "fx-4", "source": "fixtures", "url": "https://example.com/jobs/4", "title": "Backend Engineer (Python)",
     "company": "Umbrella Labs", "location": "Remote", "remote": True, "apply_email": "careers@umbrella.example",
     "description": "Requirements\nPython, SQL and PostgreSQL\nDocker\nLLM or RAG experience\nNice to have\nKafka"},
    {"id": "fx-5", "source": "fixtures", "url": "https://example.com/jobs/5", "title": "Senior Backend Engineer",
     "company": "Acme Cloud", "location": "Remote", "remote": True,
     "description": "Duplicate cross-post of job 1 on another board. Requirements\nPython"},
    {"id": "fx-6", "source": "fixtures", "url": "https://example.com/jobs/6", "title": "Security Engineer",
     "company": "Stark Defense", "location": "DC", "remote": False,
     "description": "Requirements\nPython\nclearance required\nAWS"},
]

SAMPLE_EMAILS = [
    {"id": "m1", "sender": "recruiting@acme.example", "subject": "Acme Cloud – next steps",
     "body": "Hi Alex, we'd love to schedule a call. Book a time: https://calendly.com/acme/intro or Tue Oct 7 at 2pm PT."},
    {"id": "m2", "sender": "no-reply@umbrella.example", "subject": "Your application to Umbrella Labs",
     "body": "Thank you for applying. Unfortunately we are not moving forward at this time."},
]
