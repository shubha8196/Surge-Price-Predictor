'''
Script that handles the main functionality of the whole project. All the API calls including Oauth authentication, google maps, uber, lyft and weather APIs are done from here. This script acts as an interface between the UI, the API calls and the machine learning models
'''
from flask import Flask
import json

import configuration_files.software_configuration as config
from utils.user import User
from utils.weather_information import weather_information

from datetime import timedelta
from flask import Flask, render_template, url_for, redirect, request, session
from authlib.integrations.flask_client import OAuth
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)


'''
Required Flask application, Oauth, Session Management Initializations
'''

app = Flask(__name__, static_url_path='',
                  static_folder='build',
                  template_folder='templates')


oauth = OAuth(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.needs_refresh_message = (u"Session timedout, please re-login")
login_manager.needs_refresh_message_category = "info"


'''
Read credentials from the configuration file and add it to the app configuration
'''
app.config['SECRET_KEY'] = config.google_oauth_credentials['secret_key']
app.config['GOOGLE_CLIENT_ID'] = config.google_oauth_credentials['google_client_id']
app.config['GOOGLE_CLIENT_SECRET'] = config.google_oauth_credentials['google_client_secret']


'''
Initialize Google oauth registration details, common for all the oauth configurations
'''
google = oauth.register(
    name = 'google',
    client_id = app.config["GOOGLE_CLIENT_ID"],
    client_secret = app.config["GOOGLE_CLIENT_SECRET"],
    access_token_url = 'https://accounts.google.com/o/oauth2/token',
    access_token_params = None,
    authorize_url = 'https://accounts.google.com/o/oauth2/auth',
    authorize_params = None,
    api_base_url = 'https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint = 'https://openidconnect.googleapis.com/v1/userinfo',  # This is only needed if using openId to fetch user info
    client_kwargs = {'scope': 'openid email profile'},
)


@login_manager.user_loader
def loadUser(user_id):
    '''
    This is a functionality of the login_manager from flask_login. The goal is return the loaded user in the current context
    
    param: user_id: Unique ID string returned by the Google Oauth
    return: user: Object of user class, if user is old one, else returns None
    '''
    
    return User.get(user_id)



@app.route("/logout")
@login_required
def logout():    
    '''
    This is a functionality of the login_manager from flask_login. Log the user out from the application once the logout button is pressed or the seesion is timed out
    
    param: none
    return: none (Redirects to the home page)
    '''
    
    logout_user()
    return redirect(url_for("index"))


@app.before_request
def beforeRequest():
    '''
    Setting logout time in case of inactivity
    param, return : None
    '''
    
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=config.user['session_timeout'])

    
@app.route("/")
def index():
    '''
    Homepage for the end user, which shows the google login button
    '''
    
    if current_user.is_authenticated:
        
        data={'name':current_user.name}
        return render_template('template_page2.html', data=data)
            
    else:
        return render_template('login_index.html')

    
@app.route('/login')
def googleLogin():
    '''
    Google login route for authorizing using Oauth
    
    param: none
    return: none (Redirect the context to the redirect URL in the Oauth configuration on Google console)
    '''
    
    google = oauth.create_client('google')
    redirected_url = url_for('googleAuthorize', _external=True)
    return google.authorize_redirect(redirected_url)


@app.route('/login/google/authorize')
def googleAuthorize():
    '''
    Google authorization route. Gets the user information from Google once the user is authorized. If the user already exists in the database the user information is loaded in context, else new entry is created for the user in the database. If the authentication fails, the user is directed back to the login page.
    
    param: none
    return: none (Redirect to the home page where the user enters the information and gets cab price
    '''
    
    google = oauth.create_client('google')
    token = google.authorize_access_token()
    user_info = google.get('userinfo').json()
    print (user_info["id"], user_info['name'], user_info['email'])
    
    if user_info.get("verified_email"):
        unique_id = user_info["id"]
        user_email = user_info["email"]
        user_name = user_info["name"]
    else:
        return "User email not available or not verified by Google.", 400
        
    user = User.get(unique_id)
    
    if user is not None:
        login_user(user)
    else:
        user=User(unique_id, user_name, user_email)
        user_created = user.create(unique_id, user_name, user_email)
        if user_created == False:
            return "User creation in the database failed"
    
    login_user(user)
    print ("Google Login Successful")

    return redirect(url_for("index"))


@app.route("/getCabPrice")
def run_main():
    '''
    This API handles the main business logic of the whole application. Calls the Google Maps API to get the latitude and longitude for source and destination. Calls the openweathermap API to get the weather details. Calls the model inference APIs for surge price classification and linear regression for calculating the dynamic price for uber and lyft APIs.
     
    param: source, destination, cab_price
    return: json object for result
    '''
    print ("hi")
    
    source = request.form['source']
    print (source)
    destination = request.args.get('destination')
    uber_cab_type = request.args.get('uber_cab_type')
    lyft_cab_type = request.args.get('lyft_cab_type')
    
    print (source, destination, uber_cab_type, lyft_cab_type)
    source_latitude, source_longitude=google_maps(source)
    destination_latitude, destination_longitude=google_maps(destination)
    distance, ETA = google_maps_distance_matrix(source, destination)
    
    source_latitude='10.25'
    source_longitude='100.25'
    destination_latitude='12.5'
    destination_longitude='1000'
    distance='0.2'
    ETA=15
    
    # Call uber and lyft API
    uber_original_surge='1.5'
     
    # Lyft not available
    lyft_original_surge = '1.0'
    
    
    '''
    Surge price classification model Inference
    '''
    surge_inference_df=weather_information(source_latitude, source_longitude)
    surge_inference_df['surge_mult']=[(uber_original_surge+lyft_original_surge)/2]
    
    
    '''
    Cab Price Model inference
    '''
    cab_price_inference_df = pd.DataFrame([source_latitude, source_longitude, destination_latitude, destination_longitude, distance, surge_multiplier, uber_cab_type, lyft_cab_type, uber_price, lyft_price], columns=['source_lat','source_long', 'dest_lat', 'dest_long','distance','surge_multiplier','uber_cab_type', 'lyft_cab_type', 'uber_price', 'lyft_price'])

    
    cab_price_object=CabPricePredictor(cab_price_inference_df)
    uber_price, lyft_price = cab_price_object.get_price()
    
    
    
    return json_object



if __name__ == '__main__':
    app.run()
