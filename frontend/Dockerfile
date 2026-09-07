# AI Cloud Cost Detective — frontend (React + Vite, served by nginx)
FROM node:20-alpine AS build

WORKDIR /app

# Vite inlines VITE_* env vars at BUILD time, so the API base URL must be known
# here. Override with: docker build --build-arg VITE_API_BASE=https://api.example.com
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- runtime ---
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
