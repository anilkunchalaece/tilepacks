"""
Date : Jun 13 2019
Email : anilkunchalaece@gmail.com

This script os used to download pbf files from tileserver hosted from postgres db
check tilezen vector-datasource - https://github.com/tilezen/vector-datasource
i will be using mercantile libray to get the merc coorinates from the boundingbox
ref - https://github.com/mapbox/mercantile

Tiles should be downloaded in to following format

z
|
|-x
| |-y1
| |-y2
| |-y3

Top level 1 dir is Z i.e zoom level
Top level 2 dir is X -> it contains multiple Y files

First check if Z and Y exist then download all the files in to dir

Instructions :
start the server using
gunicorn -w 8 "tileserver:wsgi_server('config.yaml')" --log-level debug
from tileserver directory

"""

import mercantile
import os,shutil,sys
import requests

URL_BASE = "http://localhost:8000"

newYorkBBoxBounds = (-74.2247679463,40.5684397151,-73.8127806416,40.888971284)
zoomLevelMin = 0
zoomLevelMax = 14

dirToStoreTiles = 'out'

def createDir(dirName):
    if(checkIfDirExist(dirName)) :
        print("dir {0} exist , so not creating".format(dirName))
        return 
    os.mkdir(dirName)
    print("dir {0} created".format(dirName))

def checkIfDirExist(dirName) :
    #return true if directory exists
    return os.path.isdir(dirName)

def removeDir(dirName) :
    print("removing dir {0}".format(dirName))
    shutil.rmtree(dirName)

def downloadPbf(tileObj):
    zVal = str(tileObj.z)
    yVal = str(tileObj.y)
    xVal = str(tileObj.x)

    ##creating / checking 2 top level directories
    #create z i.e zoom directory if not exist
    zDir = os.path.join(dirToStoreTiles,zVal)
    createDir(zDir)
    
    #create x dir if not exist
    xDir = os.path.join(dirToStoreTiles,zVal,xVal)  
    createDir(xDir)

    url = URL_BASE + '/all/' + zVal + '/' + xVal + '/' + yVal + '.mvt'

    try :    
        fileResp = requests.get(url)
        print(fileResp)
        fileDest = os.path.join(dirToStoreTiles,zVal,xVal,yVal+'.pbf')
        with open(fileDest,'wb') as fh :
            fh.write(fileResp.content)
    except :
        print("trying url {0} but {1} occured".format(url,sys.exc_info()[0]))


def main():
    #create the dir to store tiles
    if checkIfDirExist(dirToStoreTiles) :
        removeDir(dirToStoreTiles)
    createDir(dirToStoreTiles)
    all_tiles = mercantile.tiles(*newYorkBBoxBounds,zooms=list(range(zoomLevelMin,zoomLevelMax+1)))
    cnt = 0
    for tile in all_tiles :
        cnt = cnt + 1
        downloadPbf(tile)    
    print("total no of pbf files are {0}".format(cnt))

if __name__ == "__main__" :
    main()