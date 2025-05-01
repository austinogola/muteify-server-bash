#!/bin/bash

set -e

ENV_NAME="spleeter-server"

# Check for conda
if ! command -v conda &> /dev/null; then
  echo "Conda not found. Installing Miniconda..."
  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
  bash miniconda.sh -b -p $HOME/miniconda
  eval "$($HOME/miniconda/bin/conda shell.bash hook)"
  conda init
  source ~/.bashrc
else
  echo "Conda is already installed."
fi

# Activate conda in this shell
eval "$(conda shell.bash hook)"

# Remove if env exists
if conda info --envs | grep -q "^$ENV_NAME"; then
  echo "Environment $ENV_NAME already exists. Removing it..."
  conda remove -y --name $ENV_NAME --all
fi

# Create and activate the environment
echo "Creating environment..."
conda env create -f env.yml
conda activate $ENV_NAME

# Start the server
echo "Starting server..."
python app.py

