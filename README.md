# Pigolia Bot

A personal automation bot designed to track and log various life events, focusing on baby-related activities such as naps and breastfeeding. This bot provides functionality for diagnostics and integrates with InfluxDB for data storage and visualization.

## Features

- **Event Tracking**: Specifically designed to log and manage nap and breastfeeding events.
- **Diagnostics**: Includes modules for monitoring and diagnosing bot operations.
- **InfluxDB Integration**: Seamlessly sends event data to InfluxDB for time-series analysis and visualization.
- **Docker Support**: Provided with Docker configurations for easy deployment and containerization.

## Project Structure

- `src/`: Contains the core Python scripts for the bot's logic, diagnostics, and InfluxDB integration.
- `docker/nap_service/`: Includes Dockerfile, docker-compose.yml, and Python script (`bot_docker_nap.py`) specifically for deploying the nap tracking service as a containerized application.

## Getting Started

To get this bot up and running:

1.  **Clone the Repository**:
    ```bash
    git clone <your-repository-url>
    cd Pigolia_bot
    ```

2.  **Docker Deployment (Recommended)**:
    Navigate to the `docker/nap_service` directory to build and run the containerized application.
    ```bash
    cd docker/nap_service
    # Create a .env file with your environment variables (e.g., InfluxDB connection details)
    # cp variables.env.example .env (if example provided)
    docker-compose up --build -d
    ```
    Ensure you have Docker and Docker Compose installed on your system.

## License

This project is open-source and licensed under the GPL-3.0 License. See the `LICENSE` file for more details.
