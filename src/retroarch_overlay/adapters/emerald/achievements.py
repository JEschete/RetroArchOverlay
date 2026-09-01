from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NearbyAchievement:
    achievement_id: int
    title: str
    map_name: str
    event_flag: str | None = None
    trainer_prefix: str | None = None


NEARBY_ACHIEVEMENTS = (
    NearbyAchievement(27592, "Let's Have a Quick Battle!", "Route103", "FLAG_DEFEATED_RIVAL_ROUTE103"),
    NearbyAchievement(537126, "Gardening Pro", "Route104_PrettyPetalFlowerShop", "FLAG_RECEIVED_WAILMER_PAIL"),
    NearbyAchievement(537204, "Good Student", "RustboroCity_PokemonSchool", "FLAG_RECEIVED_QUICK_CLAW"),
    NearbyAchievement(537208, "Crush Those Berries", "SlateportCity", "FLAG_RECEIVED_POWDER_JAR"),
    NearbyAchievement(27593, "Long Time No See!", "Route110", trainer_prefix="TRAINER_RIVAL_ROUTE_110"),
    NearbyAchievement(537127, "Whole Winstrate Won", "Route111_WinstrateFamilysHouse", "FLAG_RECEIVED_MACHO_BRACE"),
    NearbyAchievement(537215, "Lotad Tower", "Route114_LanettesHouse", "FLAG_RECEIVED_DOLL_LANETTE"),
    NearbyAchievement(537219, "Fishing Enthusiast", "Route118", "FLAG_RECEIVED_GOOD_ROD"),
    NearbyAchievement(27594, "How Much Stronger Have You Gotten?", "Route119", trainer_prefix="TRAINER_RIVAL_ROUTE_119"),
)

FEEBAS_ACHIEVEMENT_ID = 57265
ROAMER_ACHIEVEMENT_ID = 30885

GYM_MISSABLES = {
    "RustboroCity_Gym": (537116, "Battle Addict - Rustboro", 0, "Roxanne"),
    "DewfordTown_Gym": (537117, "Battle Addict - Dewford", 1, "Brawly"),
    "MauvilleCity_Gym": (537118, "Battle Addict - Mauville", 2, "Wattson"),
    "LavaridgeTown_Gym_1F": (537119, "Battle Addict - Lavaridge", 3, "Flannery"),
    "LavaridgeTown_Gym_B1F": (537119, "Battle Addict - Lavaridge", 3, "Flannery"),
    "PetalburgCity_Gym": (537120, "Battle Addict - Petalburg", 4, "Norman"),
    "FortreeCity_Gym": (537121, "Battle Addict - Fortree", 5, "Winona"),
    "MossdeepCity_Gym": (537122, "Battle Addict - Mossdeep", 6, "Tate & Liza"),
    "SootopolisCity_Gym_1F": (537123, "Battle Addict - Sootopolis", 7, "Juan"),
    "SootopolisCity_Gym_B1F": (537123, "Battle Addict - Sootopolis", 7, "Juan"),
}

TRICK_HOUSE_MISSABLES = {
    "Route110_TrickHousePuzzle1": (537241, "Trick Master Is Fabulous"),
    "Route110_TrickHousePuzzle2": (537242, "Trick Master Is Smart"),
    "Route110_TrickHousePuzzle3": (537243, "Trick Master Is Coveted"),
    "Route110_TrickHousePuzzle4": (537244, "Trick Master Is Cool"),
    "Route110_TrickHousePuzzle6": (537245, "Trick Master Is My Life"),
    "Route110_TrickHousePuzzle7": (537246, "Trick Master Is Huggable"),
    "Route110_TrickHousePuzzle8": (537247, "Trick Master I Love"),
    "Route110_TrickHouseEnd": (537248, "Nugget of Wisdom"),
}