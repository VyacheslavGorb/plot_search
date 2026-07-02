#!/bin/bash
echo "Creating data/otp directory..."
mkdir -p data/otp

echo "Downloading Mazowieckie OSM data..."
curl -L https://download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf -o data/otp/mazowieckie-latest.osm.pbf

echo "Downloading Warsaw ZTM GTFS..."
curl -L https://mkuran.pl/gtfs/warsaw.zip -o data/otp/warsaw-gtfs.zip

echo "Downloading Polish Trains GTFS (Koleje Mazowieckie, Intercity, etc.)..."
curl -L https://mkuran.pl/gtfs/polish_trains.zip -o data/otp/polish_trains-gtfs.zip

echo "Downloads complete!"
