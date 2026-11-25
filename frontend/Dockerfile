# Stage 1: Build optimized Vite React bundle
FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_ENABLE_FAILURE_SIMULATION=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_ENABLE_FAILURE_SIMULATION=${VITE_ENABLE_FAILURE_SIMULATION}

COPY . .
RUN npm run build

# Stage 2: Lightweight Nginx runtime
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
