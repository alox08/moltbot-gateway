FROM node:22-slim

RUN apt-get update && apt-get install -y ffmpeg python3-edge-tts && apt-get clean || \
    apt-get update && apt-get install -y ffmpeg && apt-get clean

WORKDIR /app

COPY package.json .
RUN npm install

COPY *.js .

CMD ["node", "bot.js"]
