FROM nginx/unit:1.26.0-python3.9

# install required environment
COPY requirements.txt /config/requirements.txt
RUN pip install --no-cache-dir -r /config/requirements.txt

COPY app /www/app

EXPOSE 80
