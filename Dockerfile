FROM node:22-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    python3 \
    python3-pip \
    --no-install-recommends && \
    pip3 install edge-tts --break-system-packages && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json .
RUN npm install

COPY *.js .

CMD ["node", "bot.js"]
