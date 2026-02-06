"""Locust load testing for Nexus API endpoints.

Run with:
    locust -f tests/locustfile.py --host http://localhost:8080
"""


from locust import HttpUser, between, task


class NexusAPIUser(HttpUser):
    """Simulates a typical user interacting with the Nexus API."""

    wait_time = between(0.5, 2)

    def on_start(self):
        """Create a conversation to use in tests."""
        resp = self.client.post("/api/conversations")
        if resp.status_code == 200:
            self.conv_id = resp.json().get("id")
        else:
            self.conv_id = None

    @task(5)
    def get_status(self):
        """Check API status — most common health check."""
        self.client.get("/api/status")

    @task(3)
    def list_conversations(self):
        """List conversations."""
        self.client.get("/api/conversations")

    @task(2)
    def get_conversation_messages(self):
        """Fetch messages for a conversation."""
        if self.conv_id:
            self.client.get(f"/api/conversations/{self.conv_id}/messages")

    @task(2)
    def list_skills(self):
        """List skills."""
        self.client.get("/api/skills")

    @task(1)
    def list_tasks(self):
        """List task queue."""
        self.client.get("/api/tasks")

    @task(1)
    def list_plugins(self):
        """List plugins."""
        self.client.get("/api/plugins")

    @task(1)
    def list_docs(self):
        """List documents."""
        self.client.get("/api/docs")

    @task(1)
    def serve_ui(self):
        """Load the main UI page."""
        self.client.get("/")


class NexusAdminUser(HttpUser):
    """Simulates an admin user hitting admin endpoints."""

    wait_time = between(1, 3)

    def on_start(self):
        """Set up admin auth headers."""
        import os
        self.admin_key = os.getenv("ADMIN_API_KEY", "change-me-to-a-random-secret")
        self.admin_headers = {"Authorization": f"Bearer {self.admin_key}"}

    @task(3)
    def get_settings(self):
        self.client.get("/api/admin/settings", headers=self.admin_headers)

    @task(2)
    def get_models(self):
        self.client.get("/api/admin/models", headers=self.admin_headers)

    @task(2)
    def get_system_info(self):
        self.client.get("/api/admin/system", headers=self.admin_headers)

    @task(1)
    def get_usage(self):
        self.client.get("/api/admin/usage", headers=self.admin_headers)

    @task(1)
    def get_plugins(self):
        self.client.get("/api/admin/plugins", headers=self.admin_headers)

    @task(1)
    def get_logs(self):
        self.client.get("/api/admin/logs", headers=self.admin_headers)
