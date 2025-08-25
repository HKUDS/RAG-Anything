"""Load testing with Locust for RAG-Anything API."""

import json
import random
from locust import HttpUser, task, between
from faker import Faker

fake = Faker()


class RAGAnythingUser(HttpUser):
    """Simulated user for load testing RAG-Anything API."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Initialize user session."""
        # Authenticate and get token
        self.token = self.get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Create a test knowledge base
        self.kb_id = self.create_test_kb()
        
    def get_auth_token(self):
        """Get authentication token."""
        # In a real scenario, you'd authenticate with actual credentials
        # For load testing, we'll use a mock token or pre-generated token
        return "test_token_for_load_testing"
    
    def create_test_kb(self):
        """Create a test knowledge base."""
        kb_data = {
            "name": f"Load Test KB {fake.uuid4()[:8]}",
            "description": "Knowledge base for load testing"
        }
        
        response = self.client.post(
            "/api/v1/kb",
            json=kb_data,
            headers=self.headers,
            catch_response=True
        )
        
        if response.status_code == 200:
            return response.json().get("kb_id", "default_kb")
        else:
            # Fall back to default KB if creation fails
            return "default_kb"
    
    @task(5)
    def health_check(self):
        """Health check endpoint (most frequent)."""
        with self.client.get("/api/v1/health", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Health check failed: {response.status_code}")
    
    @task(3)
    def query_simple(self):
        """Simple query endpoint."""
        query_data = {
            "query": fake.sentence(),
            "kb_id": self.kb_id
        }
        
        with self.client.post(
            "/api/v1/query",
            json=query_data,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code not in [200, 404]:  # 404 acceptable if KB doesn't exist
                response.failure(f"Query failed: {response.status_code}")
    
    @task(2)
    def list_knowledge_bases(self):
        """List knowledge bases."""
        with self.client.get(
            "/api/v1/kb",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"KB list failed: {response.status_code}")
    
    @task(1)
    def upload_small_file(self):
        """Upload a small text file."""
        content = fake.text(max_nb_chars=1000)
        files = {
            "file": (f"load_test_{fake.uuid4()[:8]}.txt", content.encode(), "text/plain")
        }
        
        with self.client.post(
            "/api/v1/files/upload",
            files=files,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code not in [200, 201]:
                response.failure(f"File upload failed: {response.status_code}")
    
    @task(2)
    def get_files_list(self):
        """Get list of uploaded files."""
        with self.client.get(
            "/api/v1/files",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"Files list failed: {response.status_code}")
    
    @task(1)
    def complex_query(self):
        """Complex query with filters."""
        query_data = {
            "query": fake.paragraph(),
            "kb_id": self.kb_id,
            "filters": {
                "document_type": random.choice(["pdf", "txt", "docx"]),
                "limit": random.randint(5, 20)
            },
            "include_metadata": True
        }
        
        with self.client.post(
            "/api/v1/query",
            json=query_data,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code not in [200, 404]:
                response.failure(f"Complex query failed: {response.status_code}")


class AdminUser(HttpUser):
    """Administrative user for testing admin endpoints."""
    
    wait_time = between(2, 5)  # Slower requests for admin tasks
    
    def on_start(self):
        """Initialize admin session."""
        self.token = self.get_admin_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def get_admin_token(self):
        """Get admin authentication token."""
        return "admin_token_for_load_testing"
    
    @task(3)
    def system_health(self):
        """Check detailed system health."""
        with self.client.get(
            "/api/v1/health/detailed",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"System health failed: {response.status_code}")
    
    @task(2)
    def list_all_knowledge_bases(self):
        """List all knowledge bases (admin view)."""
        with self.client.get(
            "/api/v1/admin/kb",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code not in [200, 404]:  # 404 if endpoint doesn't exist
                response.failure(f"Admin KB list failed: {response.status_code}")
    
    @task(1)
    def get_system_metrics(self):
        """Get system metrics."""
        with self.client.get("/metrics", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Metrics failed: {response.status_code}")


class BurstTrafficUser(HttpUser):
    """User that simulates burst traffic patterns."""
    
    wait_time = between(0.1, 0.5)  # Very short wait times for burst
    
    def on_start(self):
        """Initialize burst user."""
        self.token = "burst_test_token"
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    @task
    def rapid_health_checks(self):
        """Rapid health check requests."""
        with self.client.get("/api/v1/health", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Burst health check failed: {response.status_code}")


# Load testing scenarios
class LightLoadTest(RAGAnythingUser):
    """Light load testing scenario."""
    weight = 3
    wait_time = between(2, 5)


class MediumLoadTest(RAGAnythingUser):
    """Medium load testing scenario."""
    weight = 5
    wait_time = between(1, 3)


class HeavyLoadTest(RAGAnythingUser):
    """Heavy load testing scenario."""
    weight = 2
    wait_time = between(0.5, 1.5)


# Custom load shapes
from locust.env import Environment
from locust.stats import stats_printer, stats_history
from locust.log import setup_logging
import gevent


class StepLoadShape:
    """Step load pattern for testing scalability."""
    
    step_time = 30  # 30 seconds per step
    step_load = 10  # 10 users per step
    max_users = 100
    
    def tick(self):
        run_time = self.get_run_time()
        
        if run_time < self.step_time * (self.max_users // self.step_load):
            current_step = run_time // self.step_time
            return (current_step * self.step_load, current_step * self.step_load)
        else:
            return None


# Configuration for different test scenarios
TEST_SCENARIOS = {
    "smoke": {
        "users": 5,
        "spawn_rate": 1,
        "duration": "2m"
    },
    "load": {
        "users": 50,
        "spawn_rate": 5,
        "duration": "10m"
    },
    "stress": {
        "users": 200,
        "spawn_rate": 10,
        "duration": "15m"
    },
    "spike": {
        "users": 500,
        "spawn_rate": 50,
        "duration": "5m"
    },
    "soak": {
        "users": 30,
        "spawn_rate": 2,
        "duration": "1h"
    }
}


if __name__ == "__main__":
    # Command line execution examples:
    # locust -f locustfile.py --host=http://localhost:8000
    # locust -f locustfile.py --host=http://localhost:8000 --users 50 --spawn-rate 5 --run-time 10m
    pass