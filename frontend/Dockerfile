# Build context: the repository root.
FROM node:24-alpine AS build

WORKDIR /app
# Keep in step with packageManager in frontend/package.json.
RUN npm install --global pnpm@12.18.0

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/
RUN cd frontend && pnpm install --frozen-lockfile

COPY frontend/ frontend/
RUN cd frontend && pnpm run build

FROM nginx:alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 8080
