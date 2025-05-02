# Use a Miniconda base image
FROM continuumio/miniconda3

# Set working directory
WORKDIR /app

# Copy environment YAML
COPY env.yml .

# Create and activate environment
RUN conda env create -f env.yml

# Make RUN commands use the new conda environment
SHELL ["conda", "run", "-n", "spleeter-server", "/bin/bash", "-c"]

# Copy rest of your application
COPY . .

# Expose the port your Flask app will run on (default Flask port is 5000)
EXPOSE 5000

# Command to run the Flask app using conda environment
CMD ["conda", "run", "-n", "spleeter-server", "python", "app.py"]

