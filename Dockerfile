# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir prometheus_client

# Make the script executable
RUN chmod +x byd_hvs_hvm_exporter.py

# Run the Python script when the container launches
CMD ["python", "./byd_hvs_hvm_exporter.py"]

