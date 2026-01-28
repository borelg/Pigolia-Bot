FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot script
COPY bot_docker_nap.py .

# Create directory for CSV files
RUN mkdir -p /app/data

# Set environment variables (will be overridden by Portainer)


# Run the bot
CMD ["python", "bot_docker_nap.py"]