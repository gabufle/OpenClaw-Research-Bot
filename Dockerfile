# Start with a lightweight Linux environment that has Node.js pre-installed
FROM node:22-bullseye-slim

# Install Python and pip for your scraping scripts, plus basic utilities
RUN apt-get update && apt-get install -y\
    python3 \
    python3-pip \
    nano \
    curl \
    git\
    make\
    python3-requests\
    && rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw@latest

#Install git secrets to prevent committing sensitive info 
RUN git clone https://github.com/awslabs/git-secrets.git /tmp/git-secrets \
    && cd /tmp/git-secrets \
    && make install \
    && rm -rf /tmp/git-secrets

# Set the working directory inside the container
WORKDIR /workspace

# Keep the container running in the background
CMD ["tail", "-f", "/dev/null"]