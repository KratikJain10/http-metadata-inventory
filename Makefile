.PHONY: run build down test logs clean

## Start the service (builds if needed)
run:
	docker-compose up --build

## Start in detached mode
up:
	docker-compose up --build -d

## Stop and remove containers
down:
	docker-compose down

## Stop and remove containers + volumes (wipes the database)
clean:
	docker-compose down -v

## Run the test suite inside Docker
test:
	docker-compose run --rm api pytest -v

## Run the test suite locally (requires pip install -r requirements.txt)
test-local:
	pytest -v

## Tail logs
logs:
	docker-compose logs -f api

## Open Swagger UI in the browser
docs:
	xdg-open http://localhost:8000/docs 2>/dev/null || open http://localhost:8000/docs
