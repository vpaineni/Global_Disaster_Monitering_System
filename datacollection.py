import os
import pandas as pd
import requests
import datetime
import spacy
import numpy as np
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from dotenv import load_dotenv
from urllib.parse import quote_plus
from pymongo import MongoClient
from pymongo.server_api import ServerApi
# import certifi

# # Load environment variables from .env
# load_dotenv()

# # Access them
# username = quote_plus(os.getenv("MONGO_USER"))
# password = quote_plus(os.getenv("MONGO_PASS"))
# newsapi_key = os.getenv("NEWSAPI_KEY")

# Load info from st.secerts
username = st.secrets["MONGO_USER"]
password = st.secrets["MONGO_PASS"]
news_api_key = st.secrets["NEWSAPI_KEY"]


# uri =  f"mongodb+srv://{username}:{password}@disastercluster.mtjfwab.mongodb.net/?retryWrites=true&w=majority&appName=DisasterCluster"

NEWSAPI_ENDPOINT = 'https://newsapi.org/v2/everything'

disaster_keywords = ['earthquake', 'flood', 'tsunami', 'hurricane', 'wildfire', 'forestfire', 'tornado', 'cyclone', 'volcano', 'drought', 'landslide', 'storm', 'blizzard', 'avalanche', 'heatwave']

exclude_locations = [ ] #Add Locations to exclude

# Load the spaCy English language model
nlp = spacy.load("en_core_web_sm")

# Initialize geocoder
geolocator = Nominatim(user_agent="my_geocoder")

def fetch_live_data(keyword):
    # Calculate the date 15 days ago
    fifteen_days_ago = datetime.datetime.now() - datetime.timedelta(days=15)
    
    params = {
        'apiKey': newsapi_key,
        'q': keyword,
        'from': fifteen_days_ago.strftime('%Y-%m-%d'),  # From 15 days ago
        'to': datetime.datetime.now().strftime('%Y-%m-%d'),  # To today
        'language': 'en',
    }

    response = requests.get(NEWSAPI_ENDPOINT, params=params)
    return response.json().get('articles', [])

def identify_disaster_event(title):
    if title is None:
        return np.nan
    title_lower = title.lower()
    for keyword in disaster_keywords:
        if keyword in title_lower:
            return keyword.capitalize() # Return the identified disaster type
    return np.nan # Return NaN if no keyword is found

def extract_location_ner(text):
    doc = nlp(text)
    location_ner_tags = [ent.text for ent in doc.ents if ent.label_ == 'GPE']
    return location_ner_tags

def get_coordinates(location):
    try:
        location_info = geolocator.geocode(location, timeout=10)
        if location_info:
            return pd.Series({'Latitude': location_info.latitude, 'Longitude': location_info.longitude})
        else:
            return pd.Series({'Latitude': np.nan, 'Longitude': np.nan})
    except GeocoderTimedOut:
        print(f"Geocoding timed out for {location}")
        return pd.Series({'Latitude': np.nan, 'Longitude': np.nan})
    except Exception as e:
        print(f"Error geocoding {location}: {str(e)}")
        return pd.Series({'Latitude': np.nan, 'Longitude': np.nan})

if __name__ == "__main__":
    all_live_data = []
    data = []
    for keyword in disaster_keywords:
        live_data = fetch_live_data(keyword)
        data.extend(live_data) # Use extend to add all articles from the keyword
        
        # print(f"Fetched {len(live_data)} articles for keyword: {keyword}")

        df = pd.DataFrame(data)
        df.drop_duplicates(subset='url', inplace=True) # Drop duplicates based on URL

        # print(df.head())

        # Filter the DataFrame to only include articles with disaster keywords in the title
        keyword_pattern = '|'.join(disaster_keywords) # Create a regex pattern
        df_filtered = df[df['title'].str.contains(keyword_pattern, case=False, na=False)].copy()

        for index, row in df_filtered.iterrows(): # Iterate through the filtered DataFrame
            published_at = row.get('publishedAt', datetime.datetime.now(datetime.UTC))
            disaster_event = identify_disaster_event(row['title']) # Use the improved function

            # Extract locations from title and description
            title_locations = extract_location_ner(row['title'])
            description_locations = extract_location_ner(row.get('description') if row.get('description') is not None else '')
            combined_locations_ner = list(set(title_locations + description_locations)) # Combine and remove duplicates

            filtered_article = {
                'title': row['title'],
                'disaster_event': disaster_event,
                'timestamp': published_at,
                'source': row['source'],
                'url': row['url'],
                'location_ner': combined_locations_ner # Store the combined locations
            }
            all_live_data.append(filtered_article)
    
    df = pd.DataFrame(all_live_data)

    print(df.head())

    df.drop_duplicates(subset='title', inplace=True)
    df['source'] = df['source'].apply(lambda x: x['name'])
 
    def fun(text_list):
        country, region, city = np.nan, np.nan, np.nan
        if isinstance(text_list, list):
            if len(text_list) >= 1:
                country = text_list[0]
            if len(text_list) >= 2:
                region = text_list[1]
            if len(text_list) >= 3:
                city = text_list[2]
        return country, region, city

    a = df['location_ner'].apply(fun)

    df[['Country', 'Region', 'City']] = pd.DataFrame(a.tolist(), index=df.index)
    # print("First 10 rows of Country, Region, City:")
    # print(df[['Country', 'Region', 'City']].head(10))

    def create_location(row):
        if pd.notna(row['City']):
            return row['City']
        elif pd.notna(row['Region']):
            return row['Region']
        elif pd.notna(row['Country']):
            return row['Country']
        else:
            return np.nan

    df['Location'] = df.apply(create_location, axis=1)
    # print("First 20 values of Location before dropna:")
    # print(df['Location'].head(20))
    # print(f"Number of NaN values in 'Location' before dropping: {df['Location'].isnull().sum()}")

    df_with_location = df.dropna(subset=['Location']).copy() # Create a new DataFrame with non-NaN locations

    # print(f"Shape of DataFrame after dropping NaN locations: {df_with_location.shape}")


    df = df[~df['url'].str.lower().str.contains('politics|yahoo|sports|entertainment|cricket')]


    def safe_get_coordinates(location):
        try:
            return get_coordinates(location)
        except Exception as e:
            print(f"Error during geocoding of '{location}': {e}")
            return pd.Series({'Latitude': np.nan, 'Longitude': np.nan})


    coordinates = df_with_location['Location'].apply(safe_get_coordinates)
    df_with_location[['Latitude', 'Longitude']] = coordinates.apply(pd.Series)
    df_final = df_with_location.dropna(subset=['Latitude', 'Longitude']).copy()

    # Drop the location_ner column before inserting
    if 'location_ner' in df_final.columns:
        df_final = df_final.drop(columns=['location_ner'])

    # MongoDB Atlas connection URI
    uri = f"mongodb+srv://{username}:{password}@disastercluster.mtjfwab.mongodb.net/?retryWrites=true&w=majority&appName=DisasterCluster"

    # client = MongoClient(
    #     uri,
    #     tls=True,
    #     tlsCAFile=certifi.where(),          # fresh CA bundle
    #     tlsDisableOCSPEndpointCheck=True,   # disable OCSP endpoint check ONLY
    #     serverSelectionTimeoutMS=60000,
    # )


    # Create a new client and connect to the server
    client = MongoClient(uri, server_api=ServerApi('1'))

    # Access the GeoNews database and disaster_info collection
    db = client["GeoNews"]
    collection = db["disaster_info"]

    # Create a DataFrame
    # print(df_final.head())

    # Delet all the existing data in the collection
    collection.delete_many({})
    print("Existing data in the collection has been deleted.")

    # Convert DataFrame to a list of dictionaries
    data_list = df_final.to_dict(orient='records')

    # Insert the data list into the collection
    try:
        result = collection.insert_many(data_list)
        print("Documents inserted successfully. IDs:", result.inserted_ids)
    except Exception as e:
        print("An error occurred:", e)

    # Indexing the collection on Latitude and Longitude

    # collection.create_index([("Latitude", 1), ("Longitude", 1)])
