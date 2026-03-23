//#########################################################################
// a C++ program that reads in lat/long/elev data from the US Geographic
// Survey website 
// Topographic data in units of 1", 3" and 30"
// http://dds.cr.usgs.gov/srtm/version2_1/
// then, for a given latitude longitude and elevation
// calculates the bearing (azimuth), dip angle, and distance to
// each of the gridded points.  It also finds the nearest neighbours
// to each of the gridded points and takes them in triplets forming
// triangles.  Points are randomly sampled on the surface of the triangle
// and the azimuth, dip angle, and distance are calculated to each. 
// In this way, the terrain is interpolated between the gridded points.
// Equation (1) in Section 4.2 of this paper shows how to randomly generate points
// uniformly on a triangle:
// http://www.cs.princeton.edu/~funk/tog02.pdf
// http://stackoverflow.com/questions/4778147/sample-random-point-in-triangle
//
// http://www.sherrytowers.com/merry_maidens_read_cgm.R
//
// Author: Sherry Towers
//         smtowers _at_ asu.edu
// Created: Nov 28th, 2013
//
// Copyright Sherry Towers, 2013, 2014
//
// This program is not guaranteed to be free of bugs and/or errors.
//
// This program can be freely used and shared as long as the author and
// copyright information in this header remain intact.
// 
// Modified by Marc Frincu
//         marc.frincu __at__ ntu.ac.uk
// Feb 22, 2021 for CUDA
// Jan 5, 2020 for OpenMP
// Sep 24, 2025 for processing a given azimuth range (for speed optimization if only a specific azimuth is interesting)
//#########################################################################
//#########################################################################
#include<iostream>
#include<fstream>
#include<vector>
#include<string>
#include<sstream>
#include<algorithm>
#include<functional>
#include<cmath>
#include<omp.h>
#include<stdio.h>
#include<string.h>
#include "time.h"

using namespace std;

//#########################################################################
// theta1 - lat observer, phi1 lon observer, theta2 lat towards, phi2 lon towards. Parameters in radians. Angle returned in degrees.
//#########################################################################
double computeAzimuthFromBearing(double theta1, double phi1, double theta2, double phi2, double pi) {
    double a, b;
    a = sin(phi2 - phi1) * cos(theta2);
    b = cos(theta1) * sin(theta2) - sin(theta1) * cos(theta2) * cos(phi2 - phi1);
    return atan2(a, b) * 180.0 / pi;
}

//#########################################################################
// lat1, long1 is the observer
//#########################################################################
void calculate_dip_angle(double lat1
                        ,double long1
                        ,double alt1
                        ,double lat2
                        ,double long2
                        ,double alt2
                        ,double pi
                        ,double& azimuth
                        ,double& dip_angle
                        ,double& dist
                        ,int lcorr_for_refraction=1
                        ,int lmeters=1){
   //###############################################################################
   // if we are going to correct for refraction, calculate the
   // distance so we can correct alt2
   // yoeli_with_viewshed_refraction_paper
   // awesome_paper_on_viewshed_analysis
   // horizon_calculation.pdf
   //###############################################################################
   double scale = 3280.84; // ft per km
   if (lmeters) scale = 1000.0;

   double theta1 = lat1*pi/180.0;
   double theta2 = lat2*pi/180.0;
   double phi1 = long1*pi/180.0;
   double phi2 = long2*pi/180.0;

   azimuth = computeAzimuthFromBearing(theta1, phi1, theta2, phi2, pi);

   // reusing variables a & b 
   double a = 6378.1370*scale; // earth ellisoid parameters
   double b = 6356.7523*scale;

   double R1 = a*a*a*a*cos(theta1)*cos(theta1)+b*b*b*b*sin(theta1)*sin(theta1);
   R1 = R1/(a*a*cos(theta1)*cos(theta1)+b*b*sin(theta1)*sin(theta1));
   R1 = sqrt(R1);
   double R2 = a*a*a*a*cos(theta2)*cos(theta2)+b*b*b*b*sin(theta2)*sin(theta2);
   R2 = R2/(a*a*cos(theta2)*cos(theta2)+b*b*sin(theta2)*sin(theta2));
   R2 = sqrt(R2);

   //###############################################################################
   // calculate the correction for refraction
   // yoeli_with_viewshed_refraction_paper
   // awesome_paper_on_viewshed_analysis
   //###############################################################################
   double dlat = (theta2-theta1);
   double dlon = (phi2-phi1);
   a = (sin(dlat/2.0)*sin(dlat/2.0))
      +(sin(dlon/2.0)*sin(dlon/2.0))*cos(theta1)*cos(theta2);
   double c = 2.0*atan2(sqrt(a),sqrt(1.0-a));
   dist = R2*c;
   double k = 0.13;
   double adiff = 0.0;
   if (lcorr_for_refraction){
     adiff = (dist*dist)*(k)/(R2*2.0);
   }

   //###############################################################################
   // now calculate the dip angle
   // a good online calculator is at   view-source:http://cosinekitty.com/compass.html
   // first calculate the cartesian coordinates of each of the points
   // gamma is the angle between the vectors
   // then calculate the dip angle
   // using law of cosines, calculate the distance between the points, w,
   // at the ends of the vectors, given that we know the angle between them
   // we also have
   // R2+h2+v = (R1+h1)/cos(gamma)
   // (thus v = (R1+h1)/cos(gamma)-R2-h2 )
   // and
   // w/sin(90-gamma) = v/sin(delta)
   // (thus sin(delta) = v*sin(90-gamma)/w)
   //###############################################################################
   double x1 = (R1+alt1)*cos(phi1)*sin(pi/2.0-theta1);
   double y1 = (R1+alt1)*sin(phi1)*sin(pi/2.0-theta1);
   double z1 = (R1+alt1)*cos(pi/2.0-theta1);
   double x2 = (R2+alt2)*cos(phi2)*sin(pi/2.0-theta2);
   double y2 = (R2+alt2)*sin(phi2)*sin(pi/2.0-theta2);
   double z2 = (R2+alt2)*cos(pi/2.0-theta2);
   double d1 = sqrt(x1*x1+y1*y1+z1*z1);
   double d2 = sqrt(x2*x2+y2*y2+z2*z2);
   double gamma = abs(acos((x1*x2+y1*y2+z1*z2)/(d1*d2)));

   double w = sqrt((R2+alt2+adiff)*(R2+alt2+adiff)
                  +(R1+alt1)*(R1+alt1)
                  -2.0*(R1+alt1)*(R2+alt2+adiff)*cos(gamma));
   double v = ((alt1+R1)/cos(gamma)-R2-alt2-adiff);
   dip_angle = -asin(v*sin(pi/2.0-gamma)/w);
   dip_angle = dip_angle*180.0/pi;

   if (0){
     double l = sqrt((R2+alt2)*(R2+alt2)
                    +(R1+alt1)*(R1+alt1)
                    -2.0*(R1+alt1)*(R2+alt2+adiff)*cos(gamma));
     double t = ((alt1+R1)/cos(gamma));
     dip_angle = asin((R2+alt2+adiff-t)/(l*sin(pi/2.0+gamma)));
     dip_angle = dip_angle*180.0/pi;
   }
   //cout << "theta1="<<theta1<<";alt1="<<alt1<<";phi1="<<phi1<<";"<<endl;
   //cout << "theta2="<<theta2<<";alt2="<<alt2<<";phi2="<<phi2<<";"<<endl;
   //cout << "R2="<<R2<<";alt2="<<alt2<<";adiff="<<adiff<<";t="<<t<<";l="<<l<<";gamma="<<gamma<<";"<< endl;
   //cout << "dip_angle = asin((R2+alt2+adiff-t)/(l*sin(pi/2+gamma)));" << endl;
}

//#########################################################################
//#########################################################################
//#########################################################################
//#########################################################################
int main(int argc, char **argv){
 // Usage: horizon_calc <seed> <latitude> <longitude> <elevation> <input_file> [target_azimuth] [azBinSize]
 //   seed           - integer seed offset for random number generator
 //   latitude       - observer latitude in decimal degrees
 //   longitude      - observer longitude in decimal degrees
 //   elevation      - observer elevation in metres (ground + observer height)
 //   input_file     - path to the lon/lat/elev text file from convert_srtm_to_xyz
 //   target_azimuth - (optional) if >= 0, only process terrain along this azimuth; -1 = full 360 (default -1)
 //   azBinSize      - (optional) half-width of azimuth filter in degrees (default 0.005)
 if (argc < 6) {
   cerr << "Usage: " << argv[0] << " <seed> <latitude> <longitude> <elevation> <input_file> [target_azimuth] [azBinSize]" << endl;
   return 1;
 }

 srand(unsigned(time(0))+atoi(argv[1]));

 omp_set_nested(1);

 cout << "azimuth dip distance\n";
 double pi = acos(-1.0);
 double mylatitude = atof(argv[2]);
 double mylongitude = atof(argv[3]);
 double myelevation = atof(argv[4]);
 double elev_shift = 0.0; 

 string inputFilePath = argv[5];
 double targetAzimuth = -1.0;   // -1 means process all azimuths (full 360)
 if (argc >= 7) targetAzimuth = atof(argv[6]);
 double azBinSize = 0.005;
 if (argc >= 8) azBinSize = atof(argv[7]);

 bool filterByAzimuth = (targetAzimuth >= 0.0);

 //########################################################################
 // read in the gridded latitude and longitude information
 //########################################################################
 stringstream ss;
 string s;
 vector<double> vlat;
 vector<double> vlong;
 vector<double> valt;
 vlat.push_back(mylatitude);
 vlong.push_back(mylongitude);
 valt.push_back(myelevation);
 ifstream myReadFile;
 myReadFile.open(inputFilePath.c_str());
 char output[100];
 double azimuthBearing;

 if (myReadFile.is_open()) {
   while (!myReadFile.eof()) {
     double num1,num2,num3;
     myReadFile >> num1 >> num2 >> num3;
     if (num3<0.0) num3=0.0;
     if (num3>0.0) num3=num3+elev_shift;

     if (filterByAzimuth) {
         azimuthBearing = computeAzimuthFromBearing(mylatitude * pi / 180.0, mylongitude * pi / 180.0, num2 * pi / 180.0, num1 * pi / 180.0, pi);
         if (azimuthBearing < 0)
             azimuthBearing += 360;
         if (abs(targetAzimuth - azimuthBearing) <= azBinSize) {
             vlong.push_back(num1);
             vlat.push_back(num2);
             valt.push_back(num3);
         }
     } else {
         vlong.push_back(num1);
         vlat.push_back(num2);
         valt.push_back(num3);
     }
  }
 } else {
   cerr << "Error: cannot open input file: " << inputFilePath << endl;
   return 1;
 }
 myReadFile.close();

//259202 iterations
//64 threads means approx 4056 per thread (8 x 507)

 //########################################################################
 // now, for each point in the file, find the 4 closest points
 //########################################################################
#pragma omp parallel for schedule(dynamic,4056) 
for (int i=0;i<vlong.size();i++){

   char *out = NULL;
   out = (char*)calloc(1, sizeof(char));

   int nclosest=4;
   if (i==0) nclosest=6; // i=0 is the lat/long of the site itself
   //######################################################################
   // vlongb, vlatb, etc are temporary vectors
   // from which we remove elements as they are found to be closest
   // wlong, wlat, walt contain the 4 closest points
   //######################################################################
   vector<double> vlongb;
   vector<double> vlatb;
   vector<double> valtb;
   vlongb = vlong;
   vlatb  = vlat;
   valtb  = valt;
   int iind = i;
   vector<double> wlong;
   vector<double> wlat;
   vector<double> walt;
   wlong.push_back(vlong[i]);
   wlat.push_back(vlat[i]);
   walt.push_back(valt[i]);
  
   for (int j=0;j<nclosest;j++){
     //####################################################################
     // erase the iind'th element from the vectors
     //####################################################################
     vlongb.erase(vlongb.begin()+iind);
     vlatb.erase(vlatb.begin()+iind);
     valtb.erase(valtb.begin()+iind);
     //####################################################################
     // calculate (vlong-vlong[i]) and (vlat-vlat[i])
     //####################################################################
     vector<double> d1 = vlongb;
     transform(vlongb.begin()
              ,vlongb.end()
              ,d1.begin()
              ,bind2nd(minus<double>()
              ,vlong[i]));
     vector<double> d2 = vlatb;
     transform(vlatb.begin()
              ,vlatb.end()
              ,d2.begin()
              ,bind2nd(minus<double>()
              ,vlat[i]));
     //####################################################################
     // now square the two distance vectors
     //####################################################################
     vector<double> d1b=d1;
     vector<double> d1c=d1;
     transform(d1.begin(), d1.end(), d1b.begin(), d1c.begin(), std::multiplies<double>());
     vector<double> d2b=d2;
     vector<double> d2c=d2;
     transform(d2.begin(), d2.end(), d2b.begin(), d2c.begin(), std::multiplies<double>());
     //####################################################################
     // and add them
     //####################################################################
     vector<double> d=d2b;
     transform(d1c.begin(), d1c.end(), d2c.begin(), d.begin(), std::plus<double>());
  
     //####################################################################
     // now find the index of the smallest distance to vlat[i],vlong[i]
     //####################################################################
     iind = min_element(d.begin() 
                       ,d.end())
                       -d.begin();

     //####################################################################
     // tack that point on to our temporary vectors
     //####################################################################
     wlong.push_back(vlongb[iind]);
     wlat.push_back(vlatb[iind]);
     walt.push_back(valtb[iind]);
   }

   //######################################################################
   // now iterate 100 times of the combos of the wlong,wlat,walt vector
   // that form triangles, and randomly sample points within the triangles
   // and calculate the dip angle to each
   // Equation (1) in Section 4.2 of this paper shows how to randomly generate points
   // uniformly on a triangle:
   // http://www.cs.princeton.edu/~funk/tog02.pdf
   // http://stackoverflow.com/questions/4778147/sample-random-point-in-triangle
   //######################################################################
   double A1 = wlong[0];
   double A2 = wlat[0];
   double A3 = walt[0];
   double dip_angle;
   double azimuth;
   double distance=0.0;
   if (mylatitude!=wlat[0]&&mylongitude!=wlong[0]){
     calculate_dip_angle(mylatitude
                        ,mylongitude
                        ,myelevation
                        ,wlat[0] 
                        ,wlong[0] 
                        ,walt[0]
                        ,pi
                        ,azimuth
                        ,dip_angle
                        ,distance
                        );
   }
   //cout << azimuth << " " 
   //    << dip_angle << " " 
   //    << distance/1000 << endl;
   int nsample = 1;
   if (distance<1000.0){
      nsample = 250;
   }else if (distance<2000.0){
      nsample = 100;
   }else if (distance<10000.0){
     nsample = 50;
   }else if (distance<15000.0){
     nsample = 25;
   }else if (distance<30000.0){
     nsample = 10;
   }else if (distance<50000.0){
     nsample = 10;
   }

   #pragma omp simd
   for (int j=1;j<(wlat.size()-1);j++){
     for (int k=(j+1);k<wlat.size();k++){
        if (wlat[j]!=wlat[k]&&wlong[j]!=wlong[k]){ 
          for (int niter=0;niter<nsample;niter++){
            double r1=double(rand())/double(RAND_MAX);
            double r2=double(rand())/double(RAND_MAX);
            double a = (1.0-sqrt(r1));  
            double b = sqrt(r1)*(1.0-r2);  
            double c = sqrt(r1)*r2;  
            double B1 = wlong[j];
            double B2 = wlat[j];
            double B3 = walt[j];
            double C1 = wlong[k];
            double C2 = wlat[k];
            double C3 = walt[k];
            //cout << (a*A1+b*B1+c*C1) << " "
            //     << (a*A2+b*B2+c*C2) << " "
            //     << (a*A3+b*B3+c*C3) << endl;
            double longitude = (a*A1+b*B1+c*C1);
            double latitude  = (a*A2+b*B2+c*C2);
            double elevation = (a*A3+b*B3+c*C3);
            double dip_angle;
            double azimuth;
            double distance;
            calculate_dip_angle(mylatitude
                               ,mylongitude
                               ,myelevation
                               ,latitude
                               ,longitude
                               ,elevation
                               ,pi
                               ,azimuth
                               ,dip_angle
                               ,distance
                               );
            
            if (azimuth<0.0) azimuth += 360.0;
            //cout << mylatitude << " " 
            //     << mylongitude << " " 
            //     << myelevation << " "
            //     << latitude << " " 
            //     << longitude << " " 
            //     << elevation << " " 
            //     << azimuth   << " " 
            //     << dip_angle << " " 
            //     << distance/1000.0  << endl;
/*#pragma omp ordered simd
{

            cout 
                 << azimuth   << " " 
                 << dip_angle << " " 
                 << distance/1000.0 << endl;

*/		char *tmp = NULL;
                tmp = (char*)malloc(sizeof(double) * 3 + 4);
                sprintf(tmp, "%lf %lf %lf\n", azimuth, dip_angle, distance/1000.0);

		out = (char*)realloc(out, strlen(out) + strlen(tmp) + 1);
                strcat(out,tmp);
		free(tmp);

//}
          } // end loop over sampling iterations
        } // end check that the two latitudes and longitudes are not equal
     } // end first loop over lat/long
   } // end second loop over lat/long
   cout << out;
   free (out);
 } // end loop over points in NGS file

 return 0;
}



