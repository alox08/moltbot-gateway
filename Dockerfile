FROM node:22-slim

RUN apt-get update && apt-get install -y bash && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@latest

WORKDIR /app
COPY start.sh .
RUN chmod +x start.sh

CMD ["bash", "start.sh"]
