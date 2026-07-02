import nbformat as nbf
import subprocess

nb = nbf.v4.new_notebook()

text = """\
# Plot Search - Spatial Analysis & Anomalies Detection

This notebook queries the local PostgreSQL database to analyze the results of the Phase 3 Spatial Filtering.
It checks for outliers, data distribution, and common failure reasons among the real estate parcels.
"""

code_imports = """\
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine
import warnings
warnings.filterwarnings('ignore')

# Set aesthetic parameters
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)

engine = create_engine("postgresql://postgres:password@localhost:5432/plot_search")
"""

code_query = """\
query = '''
SELECT 
    p.id,
    p.status,
    s.geometry_category,
    s.forest_distance_m,
    s.usable_building_area_m2,
    s.intersects_flood_zone,
    s.power_line_distance_m,
    s.distance_to_train_station_m,
    s.distance_to_school_m,
    s.distance_to_kindergarten_m,
    s.distance_to_drainage_m
FROM parsed_listings p
LEFT JOIN spatial_evaluations s ON p.id = s.id
WHERE p.status IN ('SPATIALLY_VALIDATED', 'FAILED_SPATIAL_RULES')
'''
df = pd.read_sql(query, engine)
print(f"Loaded {len(df)} spatial evaluations.")
display(df.head())
"""

code_stats = """\
# Basic statistics
print("--- Status Counts ---")
print(df['status'].value_counts())

print("\\n--- Geometry Categories ---")
print(df['geometry_category'].value_counts())

print("\\n--- Summary Statistics ---")
display(df.describe())
"""

code_anomalies = """\
# Anomalies Detection
print("--- ANOMALIES & EDGE CASES ---")

# 1. Extremely large usable building areas (potential parent parcel misclassified as precise)
huge_areas = df[df['usable_building_area_m2'] > 20000]
print(f"\\nParcels with > 20,000 m2 usable area (Potential unsubdivided plot labeled as precise): {len(huge_areas)}")
if not huge_areas.empty:
    display(huge_areas[['id', 'usable_building_area_m2']])

# 2. Distance anomalies (e.g., 0 distance but not failing)
zero_forest = df[(df['forest_distance_m'] == 0) & (df['status'] == 'SPATIALLY_VALIDATED')]
print(f"\\nParcels touching forest (0m) but passed validation: {len(zero_forest)}")
"""

code_visuals = """\
# Visualizations
fig, axes = plt.subplots(2, 2, figsize=(15, 12))

# 1. Usable Area Distribution
sns.histplot(data=df[df['usable_building_area_m2'] < 5000], x='usable_building_area_m2', hue='status', bins=30, ax=axes[0, 0])
axes[0, 0].set_title('Usable Building Area (<5000m2)')

# 2. Distance to Train Station
sns.histplot(data=df, x='distance_to_train_station_m', bins=30, ax=axes[0, 1])
axes[0, 1].set_title('Distance to Train Station (m)')

# 3. Distance to Power Lines
sns.histplot(data=df, x='power_line_distance_m', bins=30, ax=axes[1, 0])
axes[1, 0].set_title('Distance to Power Lines (m)')

# 4. Flood Zone Intersection
sns.countplot(data=df, x='intersects_flood_zone', hue='status', ax=axes[1, 1])
axes[1, 1].set_title('Flood Zone Intersection vs Status')

plt.tight_layout()
plt.show()
"""

nb['cells'] = [
    nbf.v4.new_markdown_cell(text),
    nbf.v4.new_code_cell(code_imports),
    nbf.v4.new_code_cell(code_query),
    nbf.v4.new_code_cell(code_stats),
    nbf.v4.new_code_cell(code_anomalies),
    nbf.v4.new_code_cell(code_visuals)
]

with open('analysis.ipynb', 'w') as f:
    nbf.write(nb, f)

print("Created analysis.ipynb. Now executing...")
subprocess.run(["uv", "run", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", "analysis.ipynb"], check=True)
print("Execution complete.")
