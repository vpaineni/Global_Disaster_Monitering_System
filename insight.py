import os
import pandas as pd
import folium
import streamlit as st
import seaborn as sns
from streamlit_folium import st_folium
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from folium.plugins import MarkerCluster  # Import MarkerCluster
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from urllib.parse import quote_plus
from wordcloud import WordCloud
import plotly.express as px
import plotly.graph_objects as go

# Load environment variables from .env
load_dotenv()

# Access the environment variables
username = quote_plus(os.getenv("MONGO_USER"))
password = quote_plus(os.getenv("MONGO_PASS"))

def main():
    uri = f"mongodb+srv://{username}:{password}@disastercluster.mtjfwab.mongodb.net/?retryWrites=true&w=majority&appName=DisasterCluster"

    exclude_locations = [ ] #Add Locations to exclude

    # Create a new client and connect to the server
    client = MongoClient(uri)

    # Access the GeoNews database and disaster_info collection
    db = client["GeoNews"]    #DATABASE NAME
    collection = db["disaster_info"] #COLLECTION NAME
    
    # Convert MongoDB cursor to DataFrame
    df = pd.DataFrame(list(collection.find()))
    df.drop_duplicates(subset='title', inplace=True)
    # Convert the 'timestamp' column to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'],errors='coerce')
    
    # Filter the DataFrame to exclude the locations in the exclude_locations list
    df = df[~df['Location'].str.lower().isin(exclude_locations)]
    df = df[~df['url'].str.lower().str.contains('politics|yahoo|sports')]
    df = df[~df['title'].str.lower().str.contains('tool|angry')]



    df['date_only'] = df['timestamp'].dt.strftime('%Y-%m-%d')

    # Drop duplicate rows based on the combination of date_only, disaster_event, and Location
    df.drop_duplicates(subset=['date_only', 'disaster_event', 'Location'], inplace=True)
    df.drop(columns=['date_only'], inplace=True)


    st.title("Geospatial Visualization for Disaster Monitoring")

    # Disaster event filter at the center
    st.subheader("Select Disaster Events")
    selected_events = st.multiselect("Select Disaster Events", ["All"] + list(df["disaster_event"].unique()), default=["All"])
    

    # Sidebar widgets for filtering
    st.sidebar.header('Filter Data')

    # current UTC now
    current_utc_now = datetime.now(timezone.utc)

    # Always guarantee start_date_past
    start_date_past = datetime(2025, 1, 1).date()  # default fallback value

    # Now try to update it dynamically if possible
    if not df.empty and 'timestamp' in df.columns:
        try:
            min_timestamp = df['timestamp'].min()
            if pd.notnull(min_timestamp):
                start_date_past = min_timestamp.to_pydatetime().date()
        except Exception as e:
            st.warning(f"Could not determine data start date dynamically: {e}")
    
    st.sidebar.caption(f"Data available from: {start_date_past}")

    # Safe default start date
    start_date_min = start_date_past

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

    # Convert Streamlit date inputs to timezone-aware datetime objects with UTC timezone
    start_date_utc = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_date_utc = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Filter dataframe based on selected filters
    if "All" in selected_events:
        filtered_df = df[(df['timestamp'] >= start_date_utc) & (df['timestamp'] <= end_date_utc)]
    else:
        filtered_df = df[(df['timestamp'] >= start_date_utc) & (df['timestamp'] <= end_date_utc) & (
                df['disaster_event'].isin(selected_events))]

    # Check if filtered_df is empty after filtering
    if filtered_df.empty:
        st.subheader(":green[No Disaster data available after filtering based on the condition]")
    else:
        col1, col2 = st.columns(2)

        with col1:

            event_location_counts = filtered_df.groupby(['disaster_event', 'Location']).size().reset_index(name='count')

            # Plot the donut chart using Plotly Express
            fig_donut = px.sunburst(
                event_location_counts,
                path=['disaster_event', 'Location'],
                values='count',
                title='Distribution of Disaster Events by Country',
                width=800,
                height=500
            )

            # Display the donut chart
            st.plotly_chart(fig_donut, use_container_width=True)

            #Fig 2

            event_counts = filtered_df['disaster_event'].value_counts().reset_index(name='count')

            # Sort the event counts to find the top 5 disaster events
            top_5_events = event_counts.head(7)

            # Plot the horizontal bar chart using Plotly Express
            fig_horizontal_bar = px.bar(
                top_5_events,
                x='count',
                y='disaster_event',
                orientation='h',
                title='Top 5 Disaster Events',
                labels={'index': 'Disaster Event', 'count': 'Count'},
                width=800,
                height=500
            )

            # Display the horizontal bar chart
            st.plotly_chart(fig_horizontal_bar, use_container_width=True)


            #Fig 3

            titles = filtered_df['title'].dropna()

            # Title for the word cloud
            st.markdown("<h3 style='font-size: 20px;'>Disaster Event Title Word Cloud</h3>", unsafe_allow_html=True)

            # Generate word cloud
            wordcloud = WordCloud(width=800, height=500, background_color='white').generate(' '.join(titles))

            # Display the word cloud using Streamlit
            st.image(wordcloud.to_array())




        with col2:
           # st.markdown("<h3 style='font-size: 20px;'>Disaster Events Distribution Over Time</h3>", unsafe_allow_html=True)
            event_counts = filtered_df.groupby([filtered_df['timestamp'].dt.date, 'disaster_event']).size().reset_index(name='count')

                # Plot the histogram using Plotly Express
            fig = px.histogram(event_counts, x='timestamp', y='count', color='disaster_event', title='Disaster Events Distribution Over Time',
                               labels={'timestamp': 'Date', 'count': 'Event Count', 'disaster_event': 'Disaster Event'},
                               template='plotly_white',width=800, height=500)
            fig.update_xaxes(type='date')
            fig.update_layout(barmode='stack',bargap=0.2)

            # Display the histogram
            st.plotly_chart(fig, use_container_width=True)


            # 2nd Diagram
            location_counts = filtered_df['Location'].value_counts().reset_index(name='count')
            location_counts.rename(columns={'index': 'Location'}, inplace=True)

            # Sort the location counts to find the top 10 countries
            top_10_countries = location_counts.head(10)

            # Plot the vertical bar chart using Plotly Express
            fig_vertical_bar = px.bar(
                top_10_countries,
                x='Location',
                y='count',
                title='Top 10 Countries by Disaster Occurrences',
                labels={'Location': 'Country', 'count': 'Count'},
                width=800,
                height=500
            )

            # Customize the appearance of the bar chart
            fig_vertical_bar.update_traces(marker_color='skyblue', marker_line_color='black', marker_line_width=1)

            # Rotate x-axis labels for better readability
            fig_vertical_bar.update_layout(xaxis_tickangle=-45)

            # Display the vertical bar chart
            st.plotly_chart(fig_vertical_bar, use_container_width=True)

            # 3rd Diagram

            st.markdown("<h3 style='font-size: 20px;'>Disaster Comparison (Current Week vs Previous Week)</h3>", unsafe_allow_html=True)
            current_week_end = datetime.utcnow().date()  # Today's date
            current_week_start = current_week_end - timedelta(days=7)
            previous_week_end = current_week_start - timedelta(days=1)  # Previous week ends 1 day before the current week starts
            previous_week_start = previous_week_end - timedelta(days=6)  # Previous week starts 6 days before it ends
    
            # Filter data for the current week and the previous week
            current_week_data = df[(df['timestamp'].dt.date >= current_week_start) & 
                                    (df['timestamp'].dt.date <= current_week_end)]
            previous_week_data = df[(df['timestamp'].dt.date >= previous_week_start) & 
                                    (df['timestamp'].dt.date <= previous_week_end)]
    
            # Count the occurrences of disaster events for each week
            current_week_count = len(current_week_data)
            previous_week_count = len(previous_week_data)
    
            # Create the gauge chart using Plotly
            fig = go.Figure(go.Indicator(
                mode="number+gauge+delta",
                value=current_week_count,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Disaster Events Count"},
                gauge={'axis': {'range': [None, max(current_week_count, previous_week_count)], 'tickwidth': 1, 'tickcolor': "darkblue"},
                        'bar': {'color': "darkblue"},
                        'bgcolor': "white",
                        'borderwidth': 2,
                        'bordercolor': "black",
                        'steps': [
                            {'range': [0, max(current_week_count, previous_week_count) * 0.4], 'color': "rgba(135, 206, 250, 0.5)"},
                            {'range': [max(current_week_count, previous_week_count) * 0.4, max(current_week_count, previous_week_count) * 0.8], 'color': "rgba(173, 216, 230, 0.5)"}],
                        'threshold': {
                            'line': {'color': "red", 'width': 4},
                            'thickness': 0.75,
                            'value': current_week_count}},
                delta={'reference': previous_week_count, 'position': "bottom", 'relative': True,
                        'increasing': {'color': "green"},
                        'decreasing': {'color': "red"},
                        'font': {'size': 18}}))
    
            # Display the gauge chart in Streamlit
            st.plotly_chart(fig, use_container_width=True)


    # Assuming df_filtered is already defined as per your instructions
    df_filtered = df[df['disaster_event'].isin(["Earthquake", "Flood", "Cyclone", "Volcano"])]

    # Filter recent events from the past 7 days
    seven_days_ago = pd.Timestamp(datetime.utcnow() - timedelta(days=5), tz="UTC")
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

