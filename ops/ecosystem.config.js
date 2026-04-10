module.exports = {
  apps: [
    {
      name: "public-api",
      cwd: ".",
      script: "uvicorn",
      args: "apps.public_api.main:app --host 0.0.0.0 --port 8000",
      interpreter: "python3",
    },
    {
      name: "admin-api",
      cwd: ".",
      script: "uvicorn",
      args: "apps.admin_api.main:app --host 0.0.0.0 --port 8001",
      interpreter: "python3",
    },
  ],
};
