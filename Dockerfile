# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Ollama connection defaults for containerised runs.
# host.docker.internal resolves to the host machine from inside Docker
# (works on Docker Desktop for Windows/macOS; Linux users may need --add-host).
# Override at runtime: docker run -e OLLAMA_BASE_URL=http://192.168.x.x:11434 ...
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENV OLLAMA_MODEL=llama3.1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# - chromium & chromium-driver: for Selenium UI automation
# - libgl1-mesa-glx & libglib2.0-0: for OpenCV computer vision support
# - curl: for network diagnostic checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files into the container at /app
COPY . .

# Expose port 5000 for the Flask Bug Triaging web server (Task 3)
EXPOSE 5000

# Set the default command to run the interactive evaluator tool
CMD ["python", "run.py"]
