from selenium import webdriver
import time
import numpy as np
import re
import os

# # this is for an uninitialized client that will be closed after the run
driver = webdriver.Chrome()

#  wait a bit for the page to load
time.sleep(1)

# # Open a website
driver.get('https://orteil.dashnet.org/cookieclicker/')

# # close the prompt

closePrompt = "Game.ClosePrompt()"
#wait for the page to load
time.sleep(1)
driver.execute_script(closePrompt)


clickCookie = "Game.ClickCookie()"

################ VV RUN ONLY ONCE VV ####################
clickGoldenCookie =  "var autoGoldenCookie = setInterval(function() { for (var h in Game.shimmers){if(Game.shimmers[h].type==\"golden\"){Game.shimmers[h].pop();}} }, 1000);"
clickGoldenCookie =  """var autoGoldenCookie = setInterval(function() {
  while (0 < Game.shimmers.length) Game.shimmers[0].pop();
}, 1000);"""
driver.execute_script(clickGoldenCookie)
driver.execute_script(clickGoldenCookie)
########################################################
object_names = ["Cursor", "Grandma", "Farm", "Mine", "Factory", "Bank", "Temple", "Wizard tower","Shipment","Alchemy lab", "Portal","Time machine"]
########################################################
getBuildings = """var buildings = Object.values(Game.Objects);
var building_info = buildings.map(function(building) {
    totalCookiesPs = building.storedTotalCps * Game.globalCpsMult
    cookiesPs = building.storedCps * Game.globalCpsMult
    heuristic = cookiesPs / building.price
    return [building.name, heuristic, building.amount, building.price, building.locked, building.storedCps, totalCookiesPs]
    
})

return building_info
"""
########################################################
getCookies = "return Game.cookies"
########################################################
getAllUpgrades = """
var upgrades = Object.values(Game.Upgrades);
var upgradeIds = upgrades.map(function(upgrade) {
    return[upgrade.id, upgrade.desc, upgrade.basePrice]
})
return upgradeIds;
"""
# Get all upgrades at the start############################
getUpgrades = """
    var upgrades = Game.UpgradesInStore;
    var upgradeIds = upgrades.map(function(upgrade) {
        return upgrade.id
    });

    return upgradeIds
    """

PlantClovers = """
if (Game.ObjectsById[2].minigame.plantsById[4].unlocked == 1){
    for (let i = 0; i < 7; i++){
        for (let j = 0; j < 7; j++){
            try {
                if (Game.ObjectsById[2].minigame.getTile(i,j)[0] == 0){
                    Game.ObjectsById[2].minigame.seedSelected = 4;
                    Game.ObjectsById[2].minigame.clickTile(i,j);
                }
            } catch (error) {
                
            }
        }
    }
}
"""

GetLucky = """
    var buffs = Game.buffs;

var getLucky = [];
for (var buffName in buffs) {
    if (
        buffName == "Frenzy" ||
        buffName == "Breakthrough" ||
        buffName == "Extra cycles" ||
        buffName == "Juicy profits" ||
        buffName == "Winning streak" ||
        buffName == "Brainstorm" ||
        buffName == "High-five" ||
        buffName == "Oiled-up" ||
        buffName == "Luxuriant harvest" ||
        buffName == "Macrocosm" ||
        buffName == "Congregation" ||
        buffName == "Cosmic nursery" ||
        buffName == "Refactoring" ||
        buffName == "Ore vein" ||
        buffName == "Righteous cataclysm" ||
        buffName == "Solar flare" ||
        buffName == "Delicious lifeforms" ||
        buffName == "Fervent adoration" ||
        buffName == "Golden ages" ||
        buffName == "Manabloom" ||
        buffName == "Deduplication" 
        // buffName == "Click frenzy"
    ) {
        getLucky.push(buffs[buffName]);
    }
}

if (getLucky.length >= 2) {
    console.log("mega frenzy");
    Game.ObjectsById[7].minigame.castSpell(Game.ObjectsById[7].minigame.spellsById[1]);

    var buffs = Game.buffs;
    // wait 2 seconds
    setTimeout(function(){
        var getLucky = [];
        for (var buffName in buffs) {
            if (
                buffName == "Frenzy" ||
                buffName == "Breakthrough" ||
                buffName == "Extra cycles" ||
                buffName == "Juicy profits" ||
                buffName == "Winning streak" ||
                buffName == "Brainstorm" ||
                buffName == "High-five" ||
                buffName == "Oiled-up" ||
                buffName == "Luxuriant harvest" ||
                buffName == "Macrocosm" ||
                buffName == "Congregation" ||
                buffName == "Cosmic nursery" ||
                buffName == "Refactoring" ||
                buffName == "Ore vein" ||
                buffName == "Righteous cataclysm" ||
                buffName == "Solar flare" ||
                buffName == "Delicious lifeforms" ||
                buffName == "Fervent adoration" ||
                buffName == "Golden ages" ||
                buffName == "Manabloom" ||
                buffName == "Deduplication" ||
                buffName == "Click frenzy" ||
                buffName == "Dragonflight"
            ) {
                getLucky.push(buffs[buffName]);
            }
        }
        if (getLucky.length >= 3) {
            //sell 400 temples
            Game.ObjectsById[7].sell(400);

            //activate loans in the bank minigame WERE GOING BIG
            Game.ObjectsById[5].minigame.takeLoan(1)
            Game.ObjectsById[5].minigame.takeLoan(2)
            Game.ObjectsById[5].minigame.takeLoan(3)

            //cast SECOND SPELL!!!!
            Game.ObjectsById[7].minigame.castSpell(Game.ObjectsById[7].minigame.spellsById[1]);
        }
    }, 1000);
}
"""
########################################################
getCookiesPs = """
            return Game.cookiesPs;
        """

########################################################
calculateAchievementBuildings = """
var achievementList = [1, 15, 50, 100, 150, 200, 250, 300, 350, 400,450, 500, 600, 650, 700, 800, 900, 1000];
var buildings = Object.values(Game.Objects);
var building_info = buildings.map(function(building) {
    for (var i = 0; i < achievementList.length; i++) {
    
        if (((achievementList[i] - building.amount < 51) && (achievementList[i] - building.amount > 0))){
        var item = achievementList[i];
        if ((building.getSumPrice(item - building.amount) < (Game.cookiesPs * 10))) {
            var  purchase = item - building.amount
            console.log(building.name, purchase)
            return [building.name, purchase];
        }
        }
    }
    return null;
});
return building_info
"""

initGoldenCookiesUpgrades = """
    goldenCookieUpgrades = [52,53,86]
    totalGoldenUpgrades = 0
    for (var i = 0; i < goldenCookieUpgrades.length; i++) {
        if(Game.UpgradesById[goldenCookieUpgrades[i]].bought == 1){
            totalGoldenUpgrades += 1;
        }
    }
    return totalGoldenUpgrades
"""

farmSugarLumps = """
if (Date.now() - Game.lumpT >= Game.lumpRipeAge){ 
    Game.clickLump()
}
"""

buyPledge = """
    if (Game.UpgradesById[74].bought == 0){
        Game.UpgradesById[74].click(event)
    }
    return 0
"""

# set up grimoire
setPantheon = """
    if (Game.ObjectsById[6].level != 0){
        try {
            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[1],1)
            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[6],2)
            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[8],3)
        } catch (error) {
            try {
                Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[1],1)
                Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[6],2)
                Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[8],3)
            } catch (error) {}
        }
    }
"""	

# spend sugar lumps
spendSugarLumps = """
    if (Game.lumps > 1){
        if (Game.ObjectsById[7].level == 0)
        {
            Game.ObjectsById[7].levelUp()
        } 
        else if (Game.ObjectsById[6].level == 0)
        {
            Game.ObjectsById[6].levelUp()

            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[1],1)
            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[6],2)
            Game.ObjectsById[6].minigame.slotGod(Game.ObjectsById[6].minigame.godsById[8],3)
        } 
        else if (Game.ObjectsById[2].level == 0)
        {
            Game.ObjectsById[2].levelUp()
        } 
        else if (Game.ObjectsById[5].level == 0)
        {
            Game.ObjectsById[5].levelUp()
        }
    }
"""	

checkStockMarket = """
//do null checks
if (Game.ObjectsById[5].minigame != null){
    for (var i = 0; i < Game.ObjectsById[5].minigame.goodsById.length; i++){
        var maxStock = Game.ObjectsById[5].minigame.getGoodMaxStock(Game.ObjectsById[5].minigame.goodsById[i]);
        if ( i > 11){
            if (Game.ObjectsById[5].minigame.goodsById[i].stock != maxStock && Game.ObjectsById[5].minigame.goodsById[i].val < 10){
                console.log("buying good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.buyGood(i, maxStock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            } 
            if (Game.ObjectsById[5].minigame.goodsById[i].stock != 0 && Game.ObjectsById[5].minigame.goodsById[i].val > 100){
                console.log("selling good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.sellGood(i, Game.ObjectsById[5].minigame.goodsById[i].stock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            }
        }  else if ( i > 5) {
            if (Game.ObjectsById[5].minigame.goodsById[i].stock != maxStock && Game.ObjectsById[5].minigame.goodsById[i].val < 5){
                console.log("buying good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.buyGood(i, maxStock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            } 
            if (Game.ObjectsById[5].minigame.goodsById[i].stock != 0 && Game.ObjectsById[5].minigame.goodsById[i].val > 80){
                console.log("selling good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.sellGood(i, Game.ObjectsById[5].minigame.goodsById[i].stock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            }
        } else {
            if (Game.ObjectsById[5].minigame.goodsById[i].stock != maxStock && Game.ObjectsById[5].minigame.goodsById[i].val < 2){
                console.log("buying good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.buyGood(i, maxStock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            } 
              if (Game.ObjectsById[5].minigame.goodsById[i].stock != 0 && Game.ObjectsById[5].minigame.goodsById[i].val > 60){
                console.log("selling good name: " + Game.ObjectsById[5].minigame.goodsById[i].name + " value: " + Game.ObjectsById[5].minigame.goodsById[i].val + " stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
                Game.ObjectsById[5].minigame.sellGood(i, Game.ObjectsById[5].minigame.goodsById[i].stock)
                console.log("stock: " + Game.ObjectsById[5].minigame.goodsById[i].stock)
            }
        }
    }
}
"""

getSaveData = """
    return Game.WriteSave(1)
"""

loadSaveData = """
function loadSave(arg1){ 
    return Game.LoadSave(arg1)
}
"""


#########################################################
def drop_trailing_s(string):
    if string.endswith("s"):
        return string[:-1]
    return string

def extract_cookie_gain(description):
    # Check if the description indicates a cookie production multiplier
    "Contains the wrath of the elders, at least for a while.<q>This is a simple ritual involving anti-aging cream, cookie batter mixed in the moonlight, and a live chicken.</q>"

    if "grandmatriarchs will return" in description or description == "" or "Activating this" in description or "Contains the wrath" in description or "Puts a permanent end" in description or "prevents golden cookies" in description:
        return 0, "all"
    if "Cookie production multiplier" in description:
        # Extract the percentage increase using regular expression
        percentage = int(re.search(r"\+(\d+)%", description).group(1))
        return percentage / 100, "all"
    if "mouse and cursor" in description:
        return 1, "clicking"
    # Check if the description indicates clicking gains
    elif "Clicking gains" in description:
        # Extract the percentage increase using regular expression
        percentage = int(re.search(r"\+(\d+)%", description).group(1))
        return percentage / 100, "clicking"
    if "milk" in description:
        return 0.25, "all"
    elif "Golden cookies" in description:
        return 2, "all"
    if "for the next" in description:
        return 0, "all"

    # Check if the description indicates building efficiency
    building_match = re.search(r"(\w+) are <b>(\w+)</b> as efficient.", description)
    if building_match:
        if " gain " in description:
            building_match = re.search(r"(\w+) gain <b>\+(\d+)%</b> CpS", description)
            building = building_match.group(1)
            efficiency = building_match.group(2)
            building = drop_trailing_s(building)
            return ((int(efficiency)*15)/100), building
        # Extract the building name and efficiency factor
        building = building_match.group(1)
        efficiency = building_match.group(2)
        building = drop_trailing_s(building)
        if efficiency == "twice":
            return 1,  building

    # For other upgrade types or unrecognized descriptions, return None or handle them as desired
    return 0.05, "all"

### MAIN ###
goldenCookieUpgrades = [52,53,86]
goldenCookieUpgradeCount = driver.execute_script(initGoldenCookiesUpgrades)  #var top keep track of how efficient holding is.

allUpgrades = driver.execute_script(getAllUpgrades)
# Extract the actual cookie gain for each upgrade
for upgrade in allUpgrades:
    cookie_gain = extract_cookie_gain(upgrade[1])
    if cookie_gain is not None:
        upgrade[1] = cookie_gain
        # print(f"Upgrade {upgrade}")
checkNewsFeed = """
Game.getNewTicker()
Game.tickerL.click();
"""

# Check if the file exists
if not os.path.exists('CookieAISaveData.txt'):
    # If not, create it
    with open('CookieAISaveData.txt', 'w') as f:
        f.write('')  # Write an empty string to create the file


# load the save data
with open('CookieAISaveData.txt', 'r') as f:
    # Read the data
    data = f.read()
    # Load the data
    driver.execute_script("return Game.LoadSave(arguments[0]);", data)

i = 0

driver.execute_script(setPantheon)

while i % 2 < 4:
    
    ##CLICK THE COOKIE##
    driver.execute_script(clickCookie)
    ####################
    ### get the upgrades and buildings from the store
    if i % 100 == 0:
        
        driver.execute_script(GetLucky)
    if i % 800 == 0:
        driver.execute_script(farmSugarLumps)
        driver.execute_script(buyPledge)
        driver.execute_script(PlantClovers)
        driver.execute_script(checkStockMarket)
    if i % 8000 == 2000:
        data = driver.execute_script(getSaveData)
        driver.execute_script(spendSugarLumps)
        formattedTimestamp = time.strftime("%Y-%m-%d %H:%M %Ss")
        print("saving data to file, time: " , formattedTimestamp)
        #save the data to a file
        with open('CookieAISaveData.txt', 'w') as f:
            # Write data to the file
            f.write(data)
    if i % 10 == 0:
        
        upgradesInStore = driver.execute_script(getUpgrades)
        allBuildings = driver.execute_script(getBuildings)
        cookiesPs = driver.execute_script(getCookiesPs)
        cookies = driver.execute_script(getCookies)
        if cookiesPs != 0:
            ### get all upgrades in the store and calculate their value
            upgradeHeuristic = []
            for upgrade in upgradesInStore:
                tempUpgrade = [x for x in allUpgrades if x[0] == upgrade]
                tempUpgrade = tempUpgrade[0].copy()
                if tempUpgrade[1][1] == 'all':
                    try:
                        tempUpgrade[1] =  (tempUpgrade[1][0] *  cookiesPs) / tempUpgrade[2] 
                    except:
                        tempUpgrade[1] =  0
                elif tempUpgrade[1][1] == 'clicking':
                    tempUpgrade[1] = (cookiesPs * tempUpgrade[1][0] * 15) / tempUpgrade[2] 
                    # print("click")
                else:
                    matchingBuilding = [x for x  in allBuildings if tempUpgrade[1][1].lower() in x[0].lower() or tempUpgrade[1][1].lower() == "factorie"]
                    matchingBuilding = matchingBuilding[0].copy()
                    # print(matchingBuilding) 
                    tempUpgrade[1] = (tempUpgrade[1][0] * matchingBuilding[6]) / tempUpgrade[2] 
                upgradeHeuristic += [tempUpgrade[1]]
            #### get the best upgrade
            if len(upgradeHeuristic) > 0:
                
                maxUpgrade = np.argmax(upgradeHeuristic)
                #### get the best building
                buildingValue = [x[1] for x in allBuildings]
                maxBuilding = np.argmax(buildingValue)

                
                # print(allBuildings[maxBuilding])
                # print("max: ", max([x[1] for x in allBuildings]))
                if i % 100 == 20:
                    driver.execute_script(checkNewsFeed)
                    achievementBuildings = driver.execute_script(calculateAchievementBuildings)
                    achievementBuildings = [x for x in achievementBuildings if x is not None]
                    
                    # print("seconds Banked", cookies/cookiesPs)
                    for achievementBuilding in achievementBuildings:
                        print("buy ", achievementBuilding[1] , " of " , achievementBuilding[0])
                        BuildingScript = f"Game.Objects['{achievementBuilding[0]}'].buy({achievementBuilding[1]})"
                        driver.execute_script(BuildingScript)

                if (upgradeHeuristic[maxUpgrade] < buildingValue[maxBuilding]):
                    if goldenCookieUpgradeCount != 3:
                        if cookies > allBuildings[maxBuilding][3]:
                            # print("seconds Banked", cookies/cookiesPs)
                            print("buy: ", allBuildings[maxBuilding][0])
                            # print("seconds Banked", cookies/cookiesPs)
                            BuildingScript = f"Game.Objects['{allBuildings[maxBuilding][0]}'].buy(1)"
                            driver.execute_script(BuildingScript)
                    elif cookies > cookiesPs * (100 * goldenCookieUpgradeCount) + allBuildings[maxBuilding][3] or ((cookiesPs > allBuildings[maxBuilding][3])  and (cookiesPs * 50 < cookies)):
                            # print("seconds Banked", cookies/cookiesPs)
                            print("buy: ", allBuildings[maxBuilding][0])
                            # print("seconds Banked", cookies/cookiesPs)
                            BuildingScript = f"Game.Objects['{allBuildings[maxBuilding][0]}'].buy(1)"
                            driver.execute_script(BuildingScript)
                else:
                    if goldenCookieUpgradeCount != 3:
                        if cookies > allUpgrades[upgradesInStore[maxUpgrade]][2]:
                            print("Seconds Banked", cookies/cookiesPs,"\nUpgrade", allUpgrades[upgradesInStore[maxUpgrade]][1], "\nseconds Banked ", cookies/cookiesPs, "\ncps: ", cookiesPs)
                            
                            UpgradeScript = f"Game.UpgradesById[{allUpgrades[upgradesInStore[maxUpgrade]][0]}].click(event)"
                            driver.execute_script(UpgradeScript)
                            if allUpgrades[upgradesInStore[maxUpgrade]][0] in goldenCookieUpgrades:
                                goldenCookieUpgradeCount += 1
                    elif cookies > cookiesPs * (100 * goldenCookieUpgradeCount) + allUpgrades[upgradesInStore[maxUpgrade]][2] or ((cookiesPs > allUpgrades[upgradesInStore[maxUpgrade]][2]) and (cookiesPs * 50 < cookies)):
                        try:
                            print("Seconds Banked", cookies/cookiesPs,"\nUpgrade", allUpgrades[upgradesInStore[maxUpgrade]][1], "\nseconds Banked ", cookies/cookiesPs, "\ncps: ", cookiesPs)
                        except: 
                            print("division by zero?")
                        UpgradeScript = f"Game.UpgradesById[{allUpgrades[upgradesInStore[maxUpgrade]][0]}].click(event)"
                        driver.execute_script(UpgradeScript)
                        if allUpgrades[upgradesInStore[maxUpgrade]][0] in goldenCookieUpgrades:
                            goldenCookieUpgradeCount += 1
                

                
                
        else:
            buildingValue = [x[1] for x in allBuildings]
            maxBuilding = np.argmax(buildingValue)
            BuildingScript = f"Game.Objects['{allBuildings[maxBuilding][0]}'].buy(1)"
            driver.execute_script(BuildingScript)
    i += 1
    ### GO SLEEP ###
    time.sleep(0.005)
    ################
print("end")
