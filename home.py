import os
import streamlit as st
import pandas as pd
import folium
import subprocess
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from streamlit_javascript import st_javascript
import plotly.express as px
from wordcloud import WordCloud
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from urllib.parse import quote_plus
from pymongo import MongoClient

# Load environment variables from .env
load_dotenv()

# Access them
username = quote_plus(os.getenv("MONGO_USER"))
password = quote_plus(os.getenv("MONGO_PASS"))

exclude_locations = [ ] #Add Locations to exclude

def main():
    # MongoDB Atlas connection URI
    @st.cache_resource
    def get_mongo_client():
        uri = f"mongodb+srv://{username}:{password}@disastercluster.mtjfwab.mongodb.net/?retryWrites=true&w=majority&appName=DisasterCluster"
        return MongoClient(uri)

    base_path = os.path.join(os.path.dirname(__file__), "Resources")

    @st.cache_data(ttl=60)
    def load_data():
        # Create a new client and connect to the server
        client = get_mongo_client()

        # Access the GeoNews database and disaster_info collection
        db = client["GeoNews"]    #DATABASE NAME
        collection = db["disaster_info"] #COLLECTION NAME

        # Convert MongoDB cursor to DataFrame
        df = pd.DataFrame(list(collection.find()))
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df[~df['title'].str.lower().str.contains('tool|angry')]

        df['date_only'] = df['timestamp'].dt.strftime('%Y-%m-%d')
        # Drop duplicate rows based on the combination of date_only, disaster_event, and Location
        df.drop_duplicates(subset=['date_only', 'disaster_event', 'Location'], inplace=True)
        df.drop(columns=['date_only'], inplace=True)

        return df

    df = load_data()

    # Session state initialization
    if "data_refresh_done" not in st.session_state:
        st.session_state.data_refresh_done = False  # prevent duplicate reruns

    # Run data collection script and refresh data
    def fetchdata():    
        # Show message + spinner
        with st.sidebar.status("Running datacollection.py...", state="running") as status:
            # Run external script
            result = subprocess.run(
                ["python", "datacollection.py"],
                capture_output=True,
                text=True
            )
            # After the script completes
            status.update(label="Completed ✓", state="complete")
            
        # Show script output
        # st.sidebar.subheader("Output:")
        # st.sidebar.code(result.stdout)
        
        # Show errors if any
        if result.stderr:
            st.sidebar.subheader("Errors:")
            st.sidebar.code(result.stderr)
        
        # clear cached MongoDB data
        load_data.clear()

        # rerun once
        st.session_state.data_refresh_done = True # mark as done to prevent re-run
        st.rerun() # force Streamlit to reload data

    # Sidebar widgets for filtering
    st.sidebar.header('Filter Data')

    # current UTC now
    current_utc_now = datetime.now(timezone.utc)

    # Always guarantee start_date_past
    start_date_past = datetime(2025, 1, 1).date()  # default fallback value

    if not st.session_state.data_refresh_done:
        if not df.empty and 'timestamp' in df.columns:
            min_timestamp = df['timestamp'].min()
            if pd.notnull(min_timestamp):
                min_date = min_timestamp.to_pydatetime().date()
                # check if data is older than 20 days
                if min_date < (current_utc_now.date() - timedelta(days=20)):
                    fetchdata()  # only run automatically if old
                    min_timestamp = df['timestamp'].min()
                    start_date_past = min_timestamp.to_pydatetime().date()
                elif pd.notnull(min_timestamp):
                    start_date_past = min_date

    st.sidebar.caption(f"Data available from: {start_date_past}")

    # Safe default start date
    start_date_min = start_date_past

    # Disaster event filter at the center
    st.title("Geospatial Visualization for Disaster Monitoring")

    st.markdown("""
    <style>
        /* Completely remove the invisible placeholder iframe added by st_folium */
        iframe[src="about:blank"] {
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* Normalize the visible map iframe */
        iframe[title="streamlit_folium.st_folium"] {
            margin-top: 0 !important;
            padding-top: 0 !important;
            display: block !important;
        }
    </style>
    """, unsafe_allow_html=True)

    selected_events = st.multiselect("Select Disaster Events", ["All"] + list(df["disaster_event"].unique()), default=["All"])

    # Now Streamlit input
    start_date = st.sidebar.date_input(
        "Start date",
        start_date_min,
        min_value=start_date_past,
        max_value=current_utc_now.date()
    )

    end_date = st.sidebar.date_input(
        "End date",
        current_utc_now.date(),
        min_value=start_date_past,
        max_value=current_utc_now.date()
    )

    if st.sidebar.button("Fetch Latest Data"):
        fetchdata()    

    # Convert Streamlit date inputs to timezone-aware datetime objects with UTC timezone
    start_date_utc = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_date_utc = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Filter dataframe based on selected filters
    if "All" in selected_events:
        filtered_df = df[(df['timestamp'] >= start_date_utc) & (df['timestamp'] <= end_date_utc)]
    elif selected_events:
        filtered_df = df[(df['timestamp'] >= start_date_utc) & (df['timestamp'] <= end_date_utc) & (
                df['disaster_event'].isin(selected_events))]
    else:
        filtered_df = df.iloc[0:0] # Empty DataFrame if no events are selected
        # Display a message if no disaster event is selected
        st.subheader(":red[No Disaster Event is selected for filtering]")

    # Check if filtered_df is empty after filtering
    if filtered_df.empty:
        st.subheader(":green[No Disaster data available after filtering based on the condition]")
    else:
        map_center = (filtered_df['Latitude'].mean(), filtered_df['Longitude'].mean())
        mymap = folium.Map(location=map_center, zoom_start=4, fullscreen_control=True)

        # Create a MarkerCluster object
        marker_cluster = MarkerCluster().add_to(mymap)

        # Function to determine custom icon path based on disaster event
        def get_custom_icon_path(disaster_event):
            # base_path = os.path.join(os.getcwd(), "Resources")
            icon_paths = {
                "Avalanche": os.path.join(base_path, "avalanche.png"),
                "Blizzard": os.path.join(base_path, "blizzard.png"),
                "Cyclone": os.path.join(base_path, "cyclone.png"),
                "Drought": os.path.join(base_path, "drought.png"),
                "Earthquake": os.path.join(base_path, "earthquake.png"),
                "Flood": os.path.join(base_path, "flood.png"),
                "Heatwave": os.path.join(base_path, "heatwave.png"),
                "Hurricane": os.path.join(base_path, "hurricane.png"),
                "Landslide": os.path.join(base_path, "landslide.png"),
                "Storm": os.path.join(base_path, "storm.png"),
                "Tornado": os.path.join(base_path, "tornado.png"),
                "Tsunami": os.path.join(base_path, "tsunami.png"),
                "Volcano": os.path.join(base_path, "eruption.png"),
                "Wildfire": os.path.join(base_path, "wildfire.png"),
            }
            return icon_paths.get(disaster_event, os.path.join(base_path, "default.png"))      

        # Add markers to the MarkerCluster object
        for index, row in filtered_df.iterrows():
            custom_icon_path = get_custom_icon_path(row['disaster_event'])
            custom_icon = folium.CustomIcon(
                icon_image=custom_icon_path,
                icon_size=(35, 35),
                icon_anchor=(15, 30),
                popup_anchor=(0, -25)
            )
            popup_content = f"<a href='{row['url']}' target='_blank'>{row['title']}</a>"
            tooltip_content = f"{row['disaster_event']}, {row['Location']}"
            folium.Marker(
                location=[row['Latitude'], row['Longitude']],
                popup=folium.Popup(popup_content, max_width=300),
                icon=custom_icon,
                tooltip=tooltip_content
            ).add_to(marker_cluster)

        # Map style options
        base_map_styles = {
            'Terrain': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            'Satellite': 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
            'Ocean': 'https://{s}.tile.stamen.com/watercolor/{z}/{x}/{y}.jpg',
            'Esri Satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            'Detail': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            'Carto Dark': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
        }

        # Add base map styles as layers
        for name, url in base_map_styles.items():
            folium.TileLayer(url, attr="Dummy Attribution", name=name).add_to(mymap)

        # Add layer control to the map with collapsed=True to hide the additional layers
        folium.LayerControl(collapsed=True).add_to(mymap)

        MAP_HEIGHT = 680
        st_folium(
            mymap,
            width="100%",
            height=MAP_HEIGHT,
            key="main_map"
    )
        
        # Display filtered data
        with st.expander(f"Disaster Data Overview"):
            expander_title = f"### Disaster Data for {'All Events' if 'All' in selected_events else ', '.join(selected_events)}"
            st.markdown(expander_title, unsafe_allow_html=True)

            columns_to_display = ['title', 'disaster_event', 'timestamp', 'source', 'url', 'Location']
            st.write(filtered_df[columns_to_display])

    # Assuming df_filtered is already defined as per your instructions
    df_filtered = df[df['disaster_event'].isin(["Earthquake", "Flood", "Cyclone", "Volcano"])]

    # Filter recent events from the past 7 days
    seven_days_ago = pd.Timestamp(datetime.now(timezone.utc) - timedelta(days=5))
    filtered_recent_events = df_filtered[df_filtered['timestamp'] >= seven_days_ago]

    # Sort filtered recent events by timestamp in descending order
    filtered_recent_events_sorted = filtered_recent_events.sort_values(by='timestamp', ascending=False)

    # Create marquee content
    marquee_content = ""
    for index, row in filtered_recent_events_sorted.iterrows():
        marquee_content += f"<a href='{row['url']}' target='_blank'>{row['title']}</a> <br><br>"

    # Define the HTML, CSS, and JavaScript for the marquee
    marquee_html = f"""
        <h1>Key Events</h1>
        <div class="marquee-container" onmouseover="stopMarquee()" onmouseout="startMarquee()">
            <div class="marquee-content">{marquee_content}</div>
        </div>
        <style>
            .marquee-container {{
                height: 100%; /* Set the height to occupy the entire sidebar */
                overflow: hidden;
            }}
            .marquee-content {{
                animation: marquee 40s linear infinite;
            }}
            @keyframes marquee {{
                0%   {{ transform: translateY(10%); }}
                100% {{ transform: translateY(-100%); }}
            }}
            .marquee-content:hover {{
                animation-play-state: paused;
            }}
        </style>
        <script>
            function stopMarquee() {{
                document.querySelector('.marquee-content').style.animationPlayState = 'paused';
            }}
            function startMarquee() {{
                document.querySelector('.marquee-content').style.animationPlayState = 'running';
            }}
        </script>
    """

    # Render the marquee in the sidebar with Streamlit
    st.sidebar.markdown(marquee_html, unsafe_allow_html=True)
