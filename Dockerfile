# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

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
