from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Achievement:
    id: int
    title: str
    description: str


ACHIEVEMENTS = (
    Achievement(50439, "Now You Can Open Doors", "Get the Thief's Key"),
    Achievement(50440, "The Adventure Begins", "Reach the main continent"),
    Achievement(50421, "Something from the Back Room", "Get the Poison Needle from Kanave"),
    Achievement(50441, "Rise and Shine", "Wake up the residents of Noaniels"),
    Achievement(50442, "It's Good to Be the King", "Become royalty"),
    Achievement(50428, "Fortune Favors the Bold", "Enjoy the nightlife of Assaram"),
    Achievement(50461, "I Didn't See Your Name on It", "Find the hidden item beneath Isis"),
    Achievement(50443, "You Can Open More Doors", "Get the Magic Key"),
    Achievement(50526, "Archaeologist", "Open all 24 chests in the pyramid"),
    Achievement(50462, "Tomb Raider", "Find the hidden item beneath the pyramid"),
    Achievement(50463, "Drop Something?", "Find the Wizard's Ring in the queen's chambers in Isis"),
    Achievement(50444, "Bolef's Path", "Convince Norud to show you the secret passage"),
    Achievement(50445, "Achoo!", "Get the Black Pepper"),
    Achievement(50429, "A Child's Toy", "Get the Water Blaster"),
    Achievement(50464, "Required Reading", "Get the Book of Satori"),
    Achievement(50431, "Lost in the Forest", "Get a Leaf from the World Tree"),
    Achievement(50466, "Winner!", "Pick the winning monster in a stadium battle"),
    Achievement(50465, "With a Little Help from My Friends", "Build a full party"),
    Achievement(50467, "A New Line of Work", "Have a character change professions"),
    Achievement(50437, "Berserker", "Cast Bikill as a fighter"),
    Achievement(50435, "Paladin", "Cast Healmore in battle as a soldier"),
    Achievement(50432, "Mage Knight", "Cast Blazemore as a soldier"),
    Achievement(50434, "So Much Magic", "Have two sages in your party"),
    Achievement(50422, "Night Time Anytime", "Get the Lamp of Darkness"),
    Achievement(50423, "Boulder Mover", "Get the Vase of Drought"),
    Achievement(50427, "Who Left That There", "Find the Staff of Thunder in Soo"),
    Achievement(50446, "You Can Open All Doors", "Get the Final Key"),
    Achievement(50447, "The Prisoner's Last Possession", "Get the Green Orb"),
    Achievement(50425, "Sonic Finder", "Get the Echoing Flute"),
    Achievement(50448, "The Man with Many Heads", "Get the Purple Orb"),
    Achievement(50449, "All By Myself", "Get the Blue Orb"),
    Achievement(50450, "Buried Treasure", "Get the Red Orb"),
    Achievement(50438, "In Memoriam", "Find the Intelligence Seed in Luzami"),
    Achievement(50527, "Spelunker", "Open all 23 chests in the cave near Samanao"),
    Achievement(50451, "The False King", "Get the Staff of Change"),
    Achievement(50452, "The Merchantville Rebellion", "Get the Yellow Orb"),
    Achievement(50453, "Land Bridge", "Set off a volcano"),
    Achievement(50454, "The Hidden Valley", "Get the Silver Orb"),
    Achievement(50455, "The Legendary Phoenix", "Hatch the giant egg in Liamland"),
    Achievement(50456, "The Archfiend is Vanquished!", "Defeat Baramos"),
    Achievement(50436, "Made for a Woman", "Get the Sword of Illusion"),
    Achievement(50426, "Music for Monsters", "Get the Silver Harp"),
    Achievement(50430, "Heroic Blocker", "Get the Shield of Heroes"),
    Achievement(50433, "Forged", "Get the Sword of Kings"),
    Achievement(50457, "The Statue Awakens", "Get the Sacred Amulet"),
    Achievement(50458, "It Only Takes One Drop", "Build the rainbow bridge"),
    Achievement(50424, "Slippery Experience", "Defeat a Metal Babble"),
    Achievement(50459, "The Foretelling", "Defeat Zoma"),
    Achievement(50651, "We're Not Scared", "Defeat Zoma without the Sphere of Light"),
    Achievement(50460, "A Legend is Born", "See the epilogue"),
)

ACHIEVEMENTS_BY_ID = {achievement.id: achievement for achievement in ACHIEVEMENTS}