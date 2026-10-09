"""Asset-free maps for background caller barriers, separate from calibration."""
import copy
from scripts.create_scenario import scenario,template


def safe_map():
    data=scenario();objects=data['objects.json']
    for name in list(objects):
        if objects[name]['type']=='hero' and objects[name]['options']['owner']=='blue':del objects[name]
    blue=data['header.json']['players']['blue'];blue.pop('mainHero',None);blue['heroes']={}
    return data


def partial_map():
    data=scenario();objects=data['objects.json']
    for name in list(objects):
        if objects[name]['type'] in ('monster','mine','resource'):del objects[name]
    terrain=[['wt00_' for _ in range(36)] for _ in range(24)]
    for low,high in ((0,10),(14,20),(26,35)):
        for row in terrain:
            for x in range(low,high+1):row[x]='dt40_'
    for x in range(11,26):terrain[12][x]='dt40_'
    data['surface_terrain.json']=terrain
    main=next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red')
    main.update(x=2,y=4);main['options']['army']=[dict(type='core:archer',amount=100)]
    helper=copy.deepcopy(main);helper.update(x=19,y=11)
    helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
    objects['hero_helper']=helper
    data['header.json']['players']['red']['heroes']['hero_helper']={'type':'christian'}
    home=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
    home['options']['army']=[dict(type='core:pikeman',amount=3000)]
    outpost=copy.deepcopy(home);outpost.update(x=20)
    outpost['options']['army']=[];objects['town_outpost']=outpost
    enemy=next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='blue')
    enemy['options']['army']=[dict(type='core:archer',amount=1000)]
    for name,x,count in (('guard_home',12,9000),('guard_outpost',23,100)):
        objects[name]=dict(type='monster',subtype='pikeman',x=x,y=12,l=0,
            template=template('AVWPIKE',['VV','VA']),options=dict(amount=count,character='hostile',neverFlees=True,noGrowing=True))
    for index,(x,y) in enumerate(((1,2),(1,22),(15,2),(20,22),(22,12))):
        objects['pickup_'+str(index)]=dict(type='resource',subtype='gold',x=x,y=y,l=0,
            template=template('AVTGOLD0',['VA']),options=dict(amount=1000))
    return data


def allocation_map():
    data=safe_map();objects=data['objects.json']
    for name in list(objects):
        if objects[name]['type'] in ('mine','resource','monster'):del objects[name]
    home=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
    home['options']['buildings']=dict(allOf=['fort','citadel','castle','blacksmith','marketplace','mageGuild1',
        'tavern','dwellingLvl1','dwellingLvl7','dwellingUpLvl7','villageHall'],
        noneOf=['shipyard']+['dwellingLvl'+str(i) for i in range(2,7)]+['dwellingUpLvl'+str(i) for i in range(1,7)])
    main=next(o for o in objects.values() if o['type']=='hero')
    helper=copy.deepcopy(main);helper.update(y=12)
    helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
    objects['hero_helper']=helper
    data['header.json']['players']['red']['heroes']['hero_helper']={'type':'christian'}
    second=copy.deepcopy(home);second.update(y=22)
    second['options']['buildings']=dict(allOf=['fort','villageHall'],noneOf=['tavern','shipyard'])
    objects['town_unassigned']=second
    return data


def stabilization_map():
    data=scenario();objects=data['objects.json']
    for name in list(objects):
        if objects[name]['type'] in ('mine','resource','monster'):del objects[name]
    home=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
    # Base is short after the controlled enemy reinforcement; current stock
    # covers the deficit without relying on a returning commander.
    home['options']['army']=[dict(type='core:pikeman',amount=570)]
    home['options']['buildings']['allOf']+=['dwellingLvl7','dwellingUpLvl7','castle','citadel']
    main=next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red')
    # The isolated gold trip keeps the commander away from both capitals.
    main.update(x=25,y=12);main['options']['army']=[dict(type='core:archer',amount=100)]
    enemy_town=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='blue')
    enemy_town['options']['buildings']['allOf']+=['dwellingLvl7','dwellingUpLvl7']
    objects['main_pickup']=dict(type='resource',subtype='gold',x=35,y=3,l=0,
        template=template('AVTGOLD0',['VA']),options=dict(amount=1000))
    objects['advance_pickup']=dict(type='resource',subtype='gold',x=16,y=12,l=0,
        template=template('AVTGOLD0',['VA']),options=dict(amount=1000))
    return data
