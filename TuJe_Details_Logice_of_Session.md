1. SET A NEW SESSION
 
Once a new session is triggered, the following steps must be completed.
 
 
 
A. Define the “Top Session mood”:
 
 
    - check session moods of the last 5 sessions. And return the most used session mood.
    - if there is no clear top session mood:
        For example:
            - Session 12 = mood “effective”
            - Session 13 = mood “playful”
            - Session 14 = mood “effective”
            - Session 15 = mood “playful”
            - Session 16 = mood “listening”
                - select between “effective” or “playful” based on what was the latest session mood “effective” or “playful”
                - in this example, it was “playful”
 
 
 
 
 
B. Calculate the “Streak30”:
 
 
    - Calculate the Streak30:
        - nbr of complete session in the last 30 days / 30 = streak30 (rounded to 2)
 
 
 
 
 
 
C. Calculate the “Streak7”:
 
 
    - Calculate the Streak7:
        - nbr of complete session in the last 7 days / 7 = streak7 (rounded to 2)
 
 
 
 
 
 
D. Calculate the “Session Boredom”:
 
 
    - The data required for this calculation:
        - last session boredom rate
        - last session level direction 
        - last session rate
        - last session mood
        - streak30
        - streak7
 
    - The calculation:
        - last session boredom rate * coefficient = session boredom (rounded to 2)
 
    - Set the coefficient = SUM (all following data) divide by the nbr of data (which is 5):
        - streak30:
            - if between 0 to 0.2 = 1.2
            - if between 0.2 to 0.4 = 1.1
            - if between 0.4 to 0.6 = 1
            - if between 0.6 to 0.8 = 0.9
            - if between 0.8 to 1 = 0.8
        - streak7:
            - if between 0 to 0.15 = 1.2
            - if between 0.15 to 0.3 = 1.1
            - if between 0.3 to 0.58 = 1
            - if between 0.58 to 0.72 = 0.9
            - if between 0.72 to 1 = 0.8
        - last session rate:
            - if between 0 to 0.4 = 1.5
            - if between 0.41 to 0.6 = 1.25
            - if between 0.61 to 0.8 = 1
            - if between 0.81 to 1 = 0.75
        - last session level direction
            - if it was “up” = 0.5
            - if it was “stable” = 1
            - if it was “down” = 1.5
        - last session mood
            - if it was “relax” or “playful” = 1.5
            - if it was “listening”, “cultural” = 1
            - if it was “effective” = 0.5
 
 
 
 
 
E. Calculate the “Session mood recommendation”:
 
 
     - The data required for this calculation:
        - streak7
        - streak30
        - session boredom 
        - last session rate
        - top session mood
 
    - The calculation:
        - Session mood recommandation = “Relax”:
            - if streak30 is between 0 to 0.4
            - and if streak7 is between 0 to 0.3
 
        - Session mood recommandation = “Playful”:
            - if streak30 is between 0 to 0.4
            - and if streak7 is between 0 to 0.3
            - and if session boredom is higher than 0.5
 
        - Session mood recommandation = “Playful”:
            - and if session boredom is higher than 0.6
 
        - Session mood recommandation = “Effective”:
            - if streak30 is between 0 to 0.6
            - and if streak7 is higher than 0.58
            - and if session boredom is lower or equal to 0.6
 
        - Session mood recommandation = “Effective”:
            - if streak30 is higher than 0.6
            - and if streak7 is higher than 0.58
            - and if session boredom is lower or equal to 0.4
 
        - if not all above, Session mood recommandation = the Top session mood
    
 
 
 
 
 
F. Calculate the “Modulo”:
 
 
    - The data required for this calculation:
        - streak7
        - streak30
        - session mood
        - last session level direction 
        - last session rate
 
 
    - The calculation:
        - session mood score * coefficient = modulo (rounded to 2)
 
 
    - Set the session mood score:
        - if session mood is “effective” = 1
        - if session mood is “listening” or “cultural” = 0.8
        - if session mood is “playful” or “relax” = 0.6
 
 
    - Set the coefficient = SUM (all following data) divide by the nbr of data (which is 4):
        - streak30:
            - if between 0 to 0.2 = 0.6
            - if between 0.2 to 0.4 = 0.7
            - if between 0.4 to 0.6 = 0.8
            - if between 0.6 to 0.8 = 0.9
            - if between 0.8 to 1 = 1
        - streak7:
            - if between 0 to 0.15 = 0.6
            - if between 0.15 to 0.3 = 0.7
            - if between 0.3 to 0.58 = 0.8
            - if between 0.58 to 0.72 = 0.9
            - if between 0.72 to 1 = 1
        - last session rate:
            - if between 0 to 0.4 = 0.7
            - if between 0.41 to 0.6 = 0.8
            - if between 0.61 to 0.8 = 0.9
            - if between 0.81 to 1 = 1
        - last session level direction
            - if it was “up” = 1
            - if it was “stable” = 0.8
            - if it was “down” = 0.6
 
 
 
 
 
 
G. Update the user session “Notions Rate”:
 
 
    - The data required for this calculation:
        - streak7
        - streak30
        - session mood
        - last session level direction 
        - last session rate
 
 
    - Pre-conditions:
        - Every time a user starts a new session and before to set the first cycle, the app needs to update notions.
        - Because we talk about notions relative to a specific user, we need to check notions in the database table session_notion filter by the last session complete.
        - Not all records of notions must be updated, update only the notions with a notion rate less then 1 and higher than 0 (so notion with a notion rate of 1 or 0 are excluded)
        - if it’s the first session of a user, so if there are no notions that exist in session_notion for this user, skip it. Don’t do “update the user session notions rate”.
        
 
 
    - The calculation:
        - last notion rate - (last notion rate * (coefficient A + coefficient B)) = updated notion rate
 
 
 
    - First part is to calculate the coefficient A (this calculation can be done only one time and re-use for all enable notions):
        - SUM (all following data)
 
        - Data 1 = streak30
            - ((streak30 rate - 0.4) / 0.1) * 0,05 = data 1 result (rounded to 2)
 
        - Data 2 = streak7
            - ((streak7 rate - 0.2) / 0.1) * 0,05 = data 2 result (rounded to 2)
 
        - Data 3 = session mood
            - if session mood is “effective” = -0.1 (it can be negative)
            - if session mood is  “cultural” or “listening” = 0.1
            - if session mood is  “relax” or “playful” = 0
 
        - Data 4 = last session level direction
            - if it’s “up” sub coefficient = 0
            - if it’s “stable” sub coefficient = 0.05
            - if it’s “down” sub coefficient = 0.1
 
        - Data 5 = last session rate
            - if the session rate is lower or equal to 60 sub coefficient = 0.1
            - if the session rate is higher than 80 sub coefficient = 0
            - if not = 0.05
 
        - Data 6 = last session date
            - calculate the difference between the current timestamp and the last session date timestamp
                - if the result is less or equal to 86400 = 0
                - if the result is higher than 259200 = 0.1
                - if not = 0.05
 
 
 
    - Second part is to calculate the coefficient B (this calculation needs to be done for each enable notions):
        - SUM (all following data)
 
        - Data 1 = notion introduction date    
            - calculate the difference between the current timestamp and the notion introduction date timestamp
                - if the result is less or equal to 604800 = 0
                - if the result is higher than 2592000 = 0.2
                - if not = 0.1
 
        - Data 2 = notion passive rate (from last session, session_notion records)
            - if the rate is between 0 to 0.05 = 0
            - if the rate is between 0.05 to 0.1 = 0.1
            - if the rate is is between 0.1 to 0.15 = 0.15
            - if the rate is more than 0.15 = 0.2
 
        - Data 3 = notion active rate (from last session, session_notion records)
            - if the rate is between 0 to 0.05 = 0
            - if the rate is between 0.05 to 0.1 = 0.1
            - if the rate is is between 0.1 to 0.15 = 0.15
            - if the rate is more than 0.15 = 0.2
 
        - Data 4 = Notion weightiness (from the brain_notion records)
            - if the weightiness is less or equal to 0.5 = 0
            - if the weightiness is more than 0.5 = 0.1
            - if the weightiness is more than 0.7 = 0.15
            - if the weightiness is more than 0.9 = 0.2
 
 
 
    - Third part, find the last notion rate:
        - find it in the database table session_notion filtered by the last session id
 
 
 
 
 
 
 
H. Calculate the user session “Notions Priority Rate”:
 
 
    - The data required for this calculation:
        - notion rate
        - notion weightiness
 
    - Which notions are concerned?
        - All notions that have been updated in the step before “update the user session notions rate”, except notions with a notion rate of 0 or 1.
 
    - The calculation:
        - (1 - notion rate) * notion weightiness = notion priority rate (rounded to 2)
 
 
 
 
 
 
 
I. Calculate the user session “Notions Complexity Rate”:
 
 
    - The data required for this calculation:
        - notion introduction date
        - current timestamp
        - notion rate
        - notion passive rate
        - notion active rate 
 
 
    - Which notions are concerned?
        - All notions that have been updated in the step before “update the user session notions rate”, except notions with a notion rate of 0 or 1.
 
    - The calculation:
        - SUM (all following data) then divided by the nbr of data (which is 5):
 
 
        - Data 1:    
            - ((current timestamp - notion introduction date timestamp) / 86400) * 0.05 = result data 1 (rounded to 2)
                - if the result data 1 is less than 0.05 = 0
 
        - Data 2:
            - 1 - notion rate = data 2 is a reversed notion rate by using minus one
        
        - Data 3:
            - (notion passive rate / 0.1) * 0.05 = data 3 (rounded to 2)
                - if the data 3 is less than 0.1 = 0
 
        - Data 4:
            - (notion active rate / 0.1) * 0.05 = data 4 (rounded to 2)
                - if the data 4 is less than 0.1 = 0
 
 
 
 
 
 
 
J. Define the “list of notions”:
 
 
    - The data required for this calculation:
        - notion complexity rate
        - notion priority rate
 
    - To do the list of notions, the app needs to sort notions of the database table session_notion of the current session:
        - first, sort according the the priority rate (descendant)
        - Include this data to sort according to the complexity rate (descendant)
 
 
 
 
 
 
K. Define the “list of intents seen”:
 
 
    - The data required for this calculation:
        - interactions displayed
 
    - Make a search for all intents used in session constrain by:
        - in the last 7 days
        - in compete cycle with cycle goal “story” or “intent”
 
 
 
 
 
L. Define the “list of subtopics seen”:
 
 
    - The data required for this calculation:
        - interactions displayed
 
    - Make a search for all subtopics used in session constrain by:
        - in the last 7 days
        - in compete cycle with cycle goal “story” or “intent”
 
 
 
 
 
M. Save data in database:
 
 
    - Save in table “session”:
        - las
 
 
 
- session id
- session rank
- nbr of cycles
- nbr of interactions
 
 
 
{
  “user_id”: “USER202505099999”,
  “user_level”: 150,  
  “user_goal”: 1,  
  “user_interest”: [
    {
      "id": “INTEREST202408090617,
      "name”: “pets”
    },    
    {
      "id": “INTEREST202408011117,
      "name”: “eiffel tower”
    },    
    {
      "id": “INTEREST202225590617,
      "name”: “yoga”
    }
  ],
  “session_id”: “SESSION202505090895",
  “session_rank”: 12,
  “session_status”: “active”,
  “session_level”: 150,
  “session_level_direction”: “up”,
  “session_nbr_cycle”: 3,
  “session_nbr_interaction”: 21,
  “streak30”: 0.6,
  “streak7”: 0.8,
  “session_mood”: “effective”,
  “top_session_mood”: “effective”,
  “top_session_mood_rate”: 0.7,
  “session_repetition”: “high”
}
 
 
 
 
 
 
 
 
………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
2. SET A NEW CYCLE
 
 
 
A. Calculate the “cycle boredom”:
 
 
 
    - if it’s the first cycle of the session:
 
        - The data required for this calculation:
            - session boredom
 
        - Calculation:
            - session boredom = cycle boredom (rounded to 2)
 
 
 
    - if it’s not the first cycle of the session:
 
        - The data required for this calculation:
            - last cycle boredom 
            - last cycle rate
            - last cycle level direction
 
        - Calculation:
            - last cycle boredom * coefficient = cycle boredom (rounded to 2)
 
        - calculate the coefficient: 
            - we need two data (last cycle rate and last cycle level direction)
            - The calculation:
                - if last cycle rate is between 0 to 0.4:
                    - if last cycle level direction is “up” = 1.25
                    - if last cycle level direction is “stable” = 1.5
                    - if last cycle level direction is “down” = 1.75
                - if last cycle rate is between 0.41 to 0.6:
                    - if last cycle level direction is “up” = 1
                    - if last cycle level direction is “stable” = 1.25
                    - if last cycle level direction is “down” = 1.5
                - if last cycle rate is between 0.61 to 0.8:
                    - if last cycle level direction is “up” = 0.75
                    - if last cycle level direction is “stable” = 1
                    - if last cycle level direction is “down” = 1.25
                - if last cycle rate is between 0.81 to 1:
                    - if last cycle level direction is “up” = 0.5
                    - if last cycle level direction is “stable” = 0.75
                    - if last cycle level direction is “down” = 1
 
 
 
 
B. Calculate the “cycle goal":
 
 
    - The data required for this calculation:
        - the cycle boredom
        - the last cycle goal
        - the cycle goal notion rate
        - the cycle goal intent rate
        - the cycle goal story rate
 
 
    - Calculation the cycle goals rate:
 
        - the cycle goal notion rate = nbr of all cycle goal filtered by “notion” in the last 7 days / 7
        - the cycle goal intent rate = nbr of all cycle goal filtered by “intent” in the last 7 days / 7
        - the cycle goal story rate = nbr of all cycle goal filtered by “story” in the last 7 days / 7
 
 
    - The calculation:
 
        - if cycle boredom is lower or equal to 0.49:
 
            - if last cycle goal is “story”:
                - if last cycle goal notion rate is lower than last cycle goal intent rate = cycle goal notion
                - if last cycle goal notion rate is higher than last cycle goal intent rate = cycle goal intent    
 
            - if last cycle goal is “notion”:
                - if last cycle goal story rate is lower than last cycle goal intent rate = cycle goal story
                - if last cycle goal story rate is higher than last cycle goal intent rate = cycle goal intent    
 
            - if last cycle goal is “intent”:
                - if last cycle goal story rate is lower than last cycle goal notion rate = cycle goal story
                - if last cycle goal story rate is higher than last cycle goal notion rate = cycle goal notion
 
 
        - if cycle boredom is between 0.5 to 0.69:
 
                - if last cycle goal story rate is at least 30% higher than last cycle goal intent = cycle goal intent
                - if last cycle goal story rate is at least 50% higher than last cycle goal notion = cycle goal notion
                - if not = cycle goal story
 
 
        - if cycle boredom is higher or equal to 0.7:
 
                - if last cycle goal story rate is at least 50% higher than last cycle goal intent = cycle goal intent
                - if last cycle goal story rate is at least 100% higher than last cycle goal notion = cycle goal notion
                - if not = cycle goal story
 
 
 
 
 
 
B. Set the “list of intents”:
 
This part still needs to be brainstorm to define what Intent should be worked during a cycle with a cycle goal “intent”.
 
 
 
 
 
C. Update the “cycle boredom":
 
 
 
    - if the user changes the cycle goal or the subtopic before to start the cycle:
 
 
        - user changes the cycle goal before to start the cycle:
            - from “notion” or “intent” to “story” = 1.5
            - from “story” to “notion” or “intent” to “story” = 0.5
            - if user dos not change cycle goal = 1
        - user changes the subtopic in a cycle goal “story”:
            - from a subtopic boredom between 0 to 0.3 to a subtopic boredom between 0 to 0.3 = 1
            - from a subtopic boredom between 0 to 0.3 to a subtopic boredom between 0.31 to 0.5 = 1.25
            - from a subtopic boredom between 0 to 0.3 to a subtopic boredom between 0.51 to 0.79 = 1.5
            - from a subtopic boredom between 0 to 0.3 to a subtopic boredom between 0.8 to 1 = 1.75
 
            - from a subtopic boredom between 0.31 to 0.5 to a subtopic boredom between 0 to 0.3 = 0.75
            - from a subtopic boredom between 0.31 to 0.5 to a subtopic boredom between 0.31 to 0.5 = 1
            - from a subtopic boredom between 0.31 to 0.5 to a subtopic boredom between 0.51 to 0.79 = 1.25
            - from a subtopic boredom between 0.31 to 0.5 to a subtopic boredom between 0.8 to 1 = 1.5
 
            - from a subtopic boredom between 0.51 to 0.79 to a subtopic boredom between 0 to 0.3 = 0.5
            - from a subtopic boredom between 0.51 to 0.79 to a subtopic boredom between 0.31 to 0.5 = 0.75
            - from a subtopic boredom between 0.51 to 0.79 to a subtopic boredom between 0.51 to 0.79 = 1
            - from a subtopic boredom between 0.51 to 0.79 to a subtopic boredom between 0.8 to 1 = 1.25
 
            - from a subtopic boredom between 0.8 to 1 to a subtopic boredom between 0 to 0.3 = 0.25
            - from a subtopic boredom between 0.8 to 1 to a subtopic boredom between 0.31 to 0.5 = 0.5
            - from a subtopic boredom between 0.8 to 1 to a subtopic boredom between 0.51 to 0.79 = 0.75
            - from a subtopic boredom between 0.8 to 1 to a subtopic boredom between 0.8 to 1 = 1
 
            - if user dos not change subtopic = 1
 
 
    - if the user does not change anything:
 
        - Do nothing, use the cycle boredom already set
 
 
 
 
 
 
D. Calculate the “cycle level":
 
 
 
- If it’s the first cycle of the session:
 
    - The data required for this calculation:
        - streak7
        - last session level direction 
        - last session rate
        - last session level
        - cycle boredom with same cycle goal
        - last cycle level with same cycle goal
 
 
    - The calculation:
 
        - Part 1: calculate the coefficient:
            - step 1: if streak7 is lower than 0.8 = 0.7 or if lower than 0.5 = 0.4 or if lower than 0.2 = 0 or if not = 1
            - step 2: if last session rate is lower than 0.8 = 0.7 or if lower than 0.6 = 0 or if not = 1
            - (step 1 * step 2) / 2 = coefficient (rounded to 2)
 
        - Part 2: apply coefficient on last session level direction:
            - if coefficient is lower than 0.5
                - if it’s “up” = 0
                - if it’s “stable” = -50
                - if it’s “down” = -50
            - if coefficient is lower than 0.8
                - if it’s “up” = 0
                - if it’s “stable” = 0
                - if it’s “down” = -50
            - if not
                - if it’s “up” = 50
                - if it’s “stable” = 0
                - if it’s “down” = 0
 
        - Part 3: final calculation:
            - last session level + result of part 2 = cycle level
 
 
 
 
 
- If it’s not the first cycle of the session:
 
 
    - The data required for this calculation:
        - last cycle level (of the current session)
        - last cycle level direction (of the current session)
        - last cycle rate (of the current session)
        - cycle boredom (of the latest cycle with the same goal)
        - cycle level (of the latest cycle with the same goal)
 
    - The calculation:
 
        - Part 1: apply last cycle rate on last level direction:
            - if last cycle rate is lower than 0.5
                - if it’s “up” = 0
                - if it’s “stable” = -50
                - if it’s “down” = -50
            - if last cycle rate is lower than 0.8
                - if it’s “up” = 0
                - if it’s “stable” = 0
                - if it’s “down” = -50
            - if not
                - if it’s “up” = 50
                - if it’s “stable” = 0
                - if it’s “down” = 0
 
        - Part 2: final calculation:
            - last cycle level + result of part 1 = cycle level
 
 
 
 
 
E. Save data in database:
 
 
    {
      “session_id”: “SESSION202505090895",
      “cycle_id”: “CYCLE202505090895",
      “cycle_rank”: 1,
      “cycle_level": 100,
     “cycle_status”: “active”,
      “cycle_goal”: “notion”,
      “cycle_boredom”: 0.32
    }
 
 
 
 
 
 
 
……………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
 
3. SET INTERACTIONS
 
 
 
A. Calculate the “Interaction User Level”:
 
 
If it’s the first interaction of the cycle:
    - cycle level = interaction user level
 
 
If it’s not the first interaction of the cycle
use the interaction user level from the last interaction complete and check if it has to be adjusted:
 
    - The data required for this calculation:
        - last interaction user level
        - last interaction score
        - cycle level direction
        - cycle rate
        - nbr of interactions complete in the cycle 
 
 
    - The calculation:
        - Increase the interaction user level by 50 if all these conditions are true:
            - the cycle rate is higher or equal to 0.8
            - the last interaction score is higher or equal to 0.8
            - the cycle level direction is “stable” or “down”
            - the nbr of interaction completed in the cycle is at least 3
 
        - Decrease the interaction user level by 50 if all these conditions are true:
            - the cycle rate is lower than 0.8
            - the last interaction score is lower than 0.6
            - the nbr of interaction completed in the cycle is at least 3
 
        - Decrease the interaction user level by 50 if all these conditions are true:
            - the cycle rate is between 0.6 and 0.79
            - the last interaction score is between 0.6 and 0.79
            - the cycle level direction is “up”
            - the nbr of interaction completed in the cycle is at least 3
 
        - Use same interaction user level if nothing above
 
 
 
 
 
B. Define the list of interactions:
 
 
 
if the cycle goal is “story”:
        
    - Part 1, set the list of subtopics:
        - search for subtopic “seen” if boredom is lower or equal to 0.29 and filter with:
            - subtopics from the list of subtopics “seen”
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
        - search for subtopic “new” if boredom is higher or equal to 0.3
            - exclude subtopics from the list of subtopics “seen"
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
    - Part 2, set the list of interactions:
        - search for interactions filter according to:
            - interactions with subtopic from the list of subtopics define in part 1
            - interactions level from is between 50 lower and 50 higher than the interaction user level
            - interactions boredom rate is higher or equal to cycle boredom (ascendant)
            - interactions type matches session mood
            - interactions expected notions contain notions with notions rate at least 0.8
            - have at least 7 interactions per subtopic, if not exclude interactions
 
    - Part 3, refine the list of interactions:
        - keep only interactions with a subtopic that contain the most interactions
 
    - Part 4, sort the list of interactions:
        - sort all interactions per combination of repetition
            - find out which combination comes first with the cycle boredom rate
            - each interaction suppose to match one type of combination, like every interaction that matches combination 1 goes first, then all interactions matches combination 2 goes after, and then the third,…
 
    - Part 5, set the first interaction:
        - Search among the list of interactions
            - interaction entry point is yes
            - interaction boredom is the closest to the cycle boredom
            - interaction level from is equal to cycle level or lower 50
 
    - Part 6, set the next interaction:
        - Search interaction in the list of interactions
            - exclude any interaction that was already used during the cycle
            - select interaction that contain in brain_interaction’s follow the last interaction id
            - the interaction must be part of a combination closest to the last interaction combination
 
 
    
 
if the cycle goal is “intent”: this part still needs to be confirmed considering that the “list of intents” is not set yet
        
    - Part 1, set the list of subtopics:
        - search for subtopic “seen” if boredom is lower or equal to 0.29 and filter with:
            - subtopics from the list of subtopics “seen”
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
        - search for subtopic “new” if boredom is higher or equal to 0.3
            - exclude subtopics from the list of subtopics “seen"
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
    - Part 2, set the list of interactions:
        - search for interactions filter according to:
            - interactions with subtopic from the list of subtopics define in part 1
            - interaction expected intent contain the intents from the list of intents
            - interactions level from is between 50 lower and 50 higher than the interaction user level
            - interactions boredom rate is higher or equal to cycle boredom (ascendant)
            - interactions type matches session mood
            - interactions expected notions contain notions with notions rate at least 0.8
            - have at least 7 interactions in total
 
    - Part 3, sort the list of interactions:
        - sort all interactions per combination of repetition
            - find out which combination comes first with the cycle boredom rate
            - each interaction suppose to match one type of combination, like every interaction that matches combination 1 goes first, then all interactions matches combination 2 goes after, and then the third,…
            - boredom
 
    - Part 4, set the first interaction:
        - Search among the list of interactions
            - interaction boredom is the closest to the cycle boredom
            - interaction level from is equal to cycle level or lower 50
 
    - Part 5, set the next interaction:
        - Search interaction in the list of interactions
            - exclude any interaction that was already used during the cycle
            - if the last interaction subtopic was used only one time during the cycle, find an interaction in the list of interaction with the same subtopic (in cycle goal intent, the same subtopic can be used only twice max), if the same subtopic has been used twice already, exclude any interactions with the same subtopic, except if there is no other interactions available in the list to complete the cycle, in this case use the same subtopic.
            - the interaction must be part of a combination equal or closest to the last interaction combination
            - boredom
            - types
 
            
 
 
if the cycle goal is “notion”:
        
    - Part 1, set the list of subtopics:
        - search for subtopic “seen” if boredom is lower or equal to 0.29 and filter with:
            - subtopics from the list of subtopics “seen”
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
        - search for subtopic “new” if boredom is higher or equal to 0.3
            - exclude subtopics from the list of subtopics “seen"
            - subtopics level from higher or equal to interaction user level (ascendant)
            - subtopics boredom rate is higher or equal to cycle boredom (ascendant)
 
    - Part 2, set the list of interactions:
        - search for interactions filter according to:
            - interactions with subtopic from the list of subtopics define in part 1
            - interaction expected notion contain the first notion from the list of notions
            - interactions level from is between 50 lower and 50 higher than the interaction user level
            - interactions boredom rate is higher or equal to cycle boredom (ascendant)
            - interactions type matches session mood
            - interactions expected intent contain intents from the list of intents already seen
            - have at least 7 interactions in total
 
    - Part 3, sort the list of interactions:
        - sort all interactions per combination of repetition
            - find out which combination comes first with the cycle boredom rate
            - each interaction suppose to match one type of combination, like every interaction that matches combination 1 goes first, then all interactions matches combination 2 goes after, and then the third,…
 
    - Part 4, set the first interaction:
        - Search among the list of interactions
            - interaction boredom is the closest to the cycle boredom
            - interaction level from is equal to cycle level or lower 50
 
    - Part 5, set the next interaction:
        - Search interaction in the list of interactions
            - exclude any interaction that was already used during the cycle
            - don’t use twice the same subtopic. exclude any interactions with the same subtopic already used during the cycle, except if there is no other interactions available in the list to complete the cycle, in this case use the same subtopic.
            - the interaction must be part of a combination equal or closest to the last interaction combination
 
 
 
 
 
 
 
E. Save data in database:
 
 
 
 
    {
      “session_id”: “SESSION202505090895",
      “cycle_id”: “CYCLE202505090895",
      “interaction_id”: “INT202505090895”,
      “interaction_rank”: 1,
      “interaction_status”: “active”
    }
 
 
 
 
 
 
…………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
 
4. CALCULATE THE INTERACTION SCORE
 
 
 
A. Calculate the “Gross Interaction Score”:
 
 
    - Calculation:
        - The gross score * Coefficient = gross interaction score (rounded to 0)
 
 
    - To set it we need several data:
        - The Gross Score
        - The Interaction Optimum Level
        - The Answer Optimum Level
        - The Cycle Level
 
 
    - Define the Gross Score:
        - If it’s the first time that the gross Interaction score of the interaction is calculated because is the first user answer, the default gross score is 100. 
        - If it’s not the first user answer of the interaction , and the interaction score of an interaction has been already calculated, then we use the Interaction score already calculated as gross score.
 
 
    - Define the Interaction Optimum Level:
        - This data is available in the database table brain_interaction filtered by the current interaction id that the user is working on
 
 
    - Define the Answer Optimum Level:
        - This data is available in the database table brain_answer filtered by the match answer we got after the completion of the transcript adjustment process. This process gives a record in the database table brain_interaction_answer which linked to a specific answer in brain_answer table.
 
 
    - Calculate the coefficient:
        - ((Answer optimum level / Interaction optimum level) + (Answer optimum level / Cycle level)) / 2 = coefficient
 
 
    - For example if it’s the first user answer of the interaction:
        - Gross score = 100
        - Interaction optimum level = 150
        - Answer optimum level = 150
        - Cycle level = 200
        - 100 * (((150 / 150) + (150 / 200)) / 2) = 87 gross interaction score (rounded to 0)        
 
 
    - For example if it’s not the first user answer of the interaction:
        - Gross score = 77
        - Interaction optimum level = 150
        - Answer optimum level = 150
        - Cycle level = 200
        - 77 * (((150 / 150) + (150 / 200)) / 2) = 67 gross interaction score (rounded to 0)
 
 
 
 
 
B. Calculate the “Bonus-Malus score”:
 
 
This part only show how bonus malus are calculated. However, the way how bonus or malus are defined during the session will be brainstorm in the future considering that each brain_bonus_malus needs to be set independently, like modular, to be trigger independantly.
 
    - To set it we need to collect any bonus or malus triggered by the user along the usage of the app, especially during a specific interaction
    - In database table brain_bonus_malus, the value of each bonus or malus found
    - Once we have collected the list of all bonus, we simply have to make the SUM (all bonus value) and SUM (all malus value)
 
    - For example:
        - Bonus A = 3
        - Bonus B = 7
        - Bonus C = 1
            - Total = 11
 
        - Malus A = 2
        - Malus B = 6
        - Malus C = 1
            - Total = 9
 
    - How to define the list of bonus or malus
        - Bonus or Malus are defined based on plenty different criterions, factors, and situations, but this will be defined in the future:
        - They can come from:
            - the brain_interaction_answer link to bonus/malus
            - special occasion like the date of the day, time, moment of the session,…
            - weird mistake like weird numbers, attitude, jokes,… from the user
            - gift bonus simply given to the user during the session to encourage the user and keep motivation up
            - … and others…
 
 
    - Calculate the Bonus score:
        - 
 
 
 
    - Calculate the Malus score:
        - 
 
 
 
    - The calculation:
        - Bonus score - (Malus score * Modulo) = bonus/malus score (rounded to 0)
 
 
 
 
 
 
C. Calculate the “Interaction Rate”:
 
    - gross interaction score + bonus/malus score = interaction score
 
 
 
 
 
 
 
D. Save data in database:
 
 
 
 
 
 
E. Data structure returned after the interaction rate is calculated:
 
 
    {
      “interaction_id”: "INT202505090895",
      “user_answer_id”: “USERANSWER202506180564”,
      "interaction_rate”: 83,
      “gross_score”: 90,
      “interaction_optimum_level”: 150,
      “answer_optimum_level": 100,
      “cycle_level": 100,
      “modulo”: 0.4,
      "list_of_bonus: [
         {
           "id": "BOMA202410021017",
          "name": "review a notion",
           "value": 10
         }
      ],
      "list_of_malus: [
        {
            "id": "BOMA202410021031",
           "name": "Over complexified",
          "value": 4
         }
       ]
    }
 
 
 
 
 
 
 
 
…………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
5. END INTERACTION (when interaction is complete)
 
 
 
 
A. Update the user session “notions rate”:
 
 
    - When and which notions rate to update?
        - Update the notions rate every time a user complete an interaction.
        - Notions must be updated after the user press the button “continue” to start the next interaction.
        - Any notions mentioned in the interaction expected notion or in the user answer after adjustement process must be updated.
 
    - Some initial considerations:
        - if the notion does not exist at all in the user session_notion database table at the date of the day of the session, the new notion rate will be calculated and updated from 0
        - if the result of the calculation of the notion rate reaches 1 or more, the notion rate must be cap to 0.99 maximum
        - if the result of the calculation of the notion rate reaches 0 or less, the notion rate must be cap to 0.01 minimum
 
    - The calculation is:
        - the score adjusted + the last notion rate = updated notion rate rounded to 2
            - the score * the coefficient = the score adjusted
 
    - Part 1 is to calculate the score:
 
        - 3 differents situations:
 
            Situation 1. When a notion is part of the interaction expected notion list and the user answer contains the notion: 
 
                - Calculate the score generate from the number of listenings and the number of attempts, during the interaction:
                    - listenings + attempts = the score
                        - listenings: 
                            - starts from 0.3 then for each extra listening minus 0.1
                            - for example, if there are 4 listenings: 0.3 minus 0.4 = -0.1
                        - attempts: 
                            - starts from 0.3 then for each extra listening minus 0.2
                            - for example, if there are 2 attempts: 0.3 minus 0.4 = -0.1
 
 
            Situation 2. When a notion is part of the interaction expected notion list but the user answer does not contain the notion 
 
                - Calculate the score generate from the number of listenings only, during the interaction:
                    - listenings = the score
                        - listenings: 
                            - starts from 0.3 then for each extra listening minus 0.1
                            - for example, if there are 4 listenings: 0.3 minus 0.4 = -0.1
 
 
            Situation 3. When a notion is not part of the interaction expected notion list but the user answer contains others notions 
 
                - Calculate the score generate from the number of attempts only, during the interaction:
                    - attempts = the score
                        - attempts: 
                            - starts from 0.3 then for each extra listening minus 0.2
                            - for example, if there are 2 attempts: 0.3 minus 0.4 = -0.1
 
 
    - Part 2 is to calculate the coefficient:
 
        - Calculate the coefficient:
            - SUM all sub coefficients (streak30, streak7, session mood, user level compare notion level, notion introduction date, notion passive rate, notion active rate, notion weightiness)
 
        - Generate each sub coefficients:
            - streak30
                - if streak30 value is lower or equal to 0.4 = 0 sub coefficient
                - every 0.1 more steak30 value add 0.05 sub coefficient
                    - example if streak30 is 0.64 so it’s 0.4 + 0.24 which is sub coefficient 0 + (twice 0.05) = 0.1
            - streak7
                - if streak7 value is lower or equal to 0.2 = 0 sub coefficient
                - every 0.1 more streak7 value add 0.05 sub coefficient    
                    - example if streak7 is 0.58 so it’s 0 + 0.38  which is sub coefficient 0 + (there times 0.05) = 0.15
            - Session mood
                - if it’s “effective” sub coefficient = -0.1 (it can be negative sub coefficient)
                - if it’s “cultural” or “listening” sub coefficient = 0.2
                - if it’s “relax” or “playful” sub coefficient = 0
            - User level compare notion level from
                - if user level is equal to notion level from sub coefficient = 0
                - if user level is 50 higher than notion level from sub coefficient = -0.1 (it can be negative sub coefficient)
                - if user level is 100 higher or more than notion level from sub coefficient = -0.2 (it can be negative sub coefficient)
            - Notion introduction date    
                - if the notion introduction date timestamp is less or equal than 604800 compare with timestamp now = 0
                - if the notion introduction date timestamp is more than 604800 compare with timestamp now = 0.1
                - if the notion introduction date timestamp is more than 2592000 compare with timestamp now = 0.2
            - Notion passive rate
                - if the rate is less or equal to 0.05 = 0
                - if the rate is more than 0.05 = 0.1
                - if the rate is more than 0.1 = 0.15
                - if the rate is more than 0.15 = 0.2
            - Notion active rate
                - if the rate is less or equal to 0.1 = 0
                - if the rate is more than 0.05 = 0.1
                - if the rate is more than 0.1 = 0.15
                - if the rate is more than 0.15 = 0.2
            - Notion weightiness
                - if the weightiness is less or equal to 0.5 = 0
                - if the weightiness is more than 0.5 = 0.1
                - if the weightiness is more than 0.7 = 0.15
                - if the weightiness is more than 0.9 = 0.2
            - Notion checked
                - user checked notion
                - user pressed hint that contain the notion that he cannot use
                - user checked vocab that contain notion
                - user checked answers that contain notion
 
        - Them SUM together all sub coefficient (some are positive and others might be negative)
 
 
    - Part 3 is to calculate the adjusted score:
 
            - before to adjust the score, check if it’s necessary to reverse the coefficient:
                - if the score’s result is positive = reverse coefficient value 
                    - if coefficient was 0.2 so we do 1 - 0.2 = 0.8
                - if the score’s result is negative = use the coefficient value
                    - if coefficient was 0.2 so we use 0.2
            - then do this: 
                - score * coefficient = adjusted score rounded to 2
                    - for example, if score is 0.4 and coefficient is 0.6 so we do 0.4 * 0.6 = 0.24
 
 
    - Part 4 is to calculate the updated notion rate:
 
        - Get from the database table session_notion the latest notion rate saved and we sum with the adjusted score:
            - last notion rate + adjusted score = Updated notion rate 
 
 
    - Part 5 is optional:
        - check if others notions must be updated
        - Then update the data in database table session_notion
 
 
 
 
 
 
B. Calculate the “speaking rate”:
 
    
    - To set it we need several data:
        - Speaking optimum level
        - Session mood
        - Interaction type
        - Nbr of answers
        - Cycle level
 
 
    - Warning! Some data might prevent calculating the speaking rate. If one those data below are true don’t calculate speaking rate:
        - If session mood is “listening”
        - If interaction type is “true/false”, “Seek and Find”, “Quiz”, “Listen and touch”
 
 
    - If data above are not true, so we can calculate the speaking rate:
 
 
        - Calculate the Gross speaking rate
            - Speaking optimum level / Cycle level = Gross speaking rate (rounded to 2)
                - if the gross speaking rate’s result is higher than 1 = cap it at 1 max
                - then calculate the gross speaking rate of all answers of the specific session_interaction
 
 
        - The calculation:
            - SUM (all Gross speaking rate of all answers) / nbr of answers = Speaking rate (rounded to 2)
 
 
 
 
 
 
C. Calculate the “comprehension rate":
 
 
    - how much the user comprehend the interaction
    - based on the comprehension optimum level
    - adjust corefficient:
        - nbr of listenings
        - hints
        - help understanding
 
 
 
 
 
D. Calculate the “accuracy rate”:
 
    - how much the answer was good pronunciation
    - how close the transcription was with vocabnotfound
    - if the brain_interaction_answer already contains mistakes = accuracy rate
    - gross accuracy rate * vocabnotfound rate
    - SUM (all session_interaction_answer’s accuracy rate) / nbr of answers
 
 
 
 
 
 
E. Calculate the “Interaction user level”:
 
    - how much the user has handle the interaction
        - Interaction level
        - Answer level
        - Interaction rate
        - Speaking rate
        - Comprehension rate
        - Accuracy rate
 
 
 
 
 
F. Update the “cycle rate”:
 
 
    - Calculation:
        - SUM(interaction rate from all interactions complete during the cycle so far) / nbr of interactions complete during the cycle so far = cycle rate (rounded to 2)
 
 
 
 
 
 
G. Calculate the “interaction boredom”:
 
 
 
    - if it’s the first interaction of the cycle:
    
        - Calculation:
            - cycle boredom = interaction boredom
    
 
 
    - if it’s not the first interaction of the cycle:
 
        - Calculation:
            - last interaction boredom * coefficient = interaction boredom rate (rounded to 2)
 
 
        - calculate the coefficient = SUM (all following 8 data) divide by the nbr of data which is 8
            - Data 1:
                - if cycle level direction is “up” = 0.5
                - if cycle level direction is “stable” = 1
                - if cycle level direction is “down” = 1.5
            - Data2: 
                - if cycle rate is lower than 0.6    = 1.5
                - if cycle rate is lower than 0.7    = 1.25
                - if cycle rate is lower than 0.8 = 1
                - if cycle rate is lower than 0.9 = 0.75
                - if not = 0.5
            - Data 3:
                - if nbr of attempts is 1 = 0.5
                - if nbr of attempts is 2 = 1
                - if nbr of attempts is 3 = 1.25
                - if nbr of attempts is 4 or more = 1.5
            - Data 4:
                - if nbr of listenings is 1 = 0.5
                - if nbr of listenings is 2 = 0.75
                - if nbr of listenings is 3 = 1
                - if nbr of listenings is 4 = 1.25
                - if nbr of listenings is 5 or more = 1.5
            - Data 5: 
                - if speaking rate is lower than 0.6    = 1.5
                - if speaking rate is lower than 0.7    = 1.25
                - if speaking rate is lower than 0.8 = 1
                - if speaking rate is lower than 0.9 = 0.75
                - if not = 0.5
            - Data 6: 
                - if nbr of hint triggered is 1 = 1
                - if nbr of hint triggered is 2 = 1.25
                - if nbr of hint triggered is 3 or more = 1.5
                - if no hint triggered = 0.5
            - Data 7:
                - if help for understanding is activated = 1
                - if help for answering is activated = 1
                - if help for both is activated = 1.5
                - if no help activated = 0,5
            - press like or dislike:
                if like = 0.5
                if dislike = 1.5
                if nothing = 1
 
 
 
 
H. Save data in database:
 
 
 
 
 
 
 
 
 
 
 
…………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
 
6. END CYCLE (when cycle is complete)
 
 
 
A. Update the “cycle rate”:
 
    - Calculation:
        - SUM(all the session_interaction filtered by cycle_id = interaction_rate) / 7 = cycle rate (rounded to 2)
 
 
 
 
 
B. Update the “cycle boredom”:
 
 
    - Calculation:
        - SUM(all the session_interaction filtered by cycle_id = boredom_rate) / 7 = cycle boredom (rounded to 2)
 
 
 
 
 
 
C. Update the “cycle level”:
 
    - Calculation:
        - SUM(all the session_interaction filtered by cycle_id = Interaction_user_level) / 7 = cycle level (rounded to 0)
 
 
 
 
 
 
D. Calculate the “cycle level direction”:
 
    - Calculation:
        - cycle level at the end of the cycle - cycle level at the beginning of the cycle = cycle level direction 
            - if the calculation result is 6 or more = up
            - if the calculation result is between -5 and 5 = stable
            - if the calculation result is -6 or less = down
 
 
 
 
 
E. Save data in database:
 
 
 
    {
      “session_id”: “SESSION202505090895",
      “cycle_id”: “CYCLE202505090895”,
      “cycle_level": 100,
      “cycle_status”: “complete”,
      “cycle_boredom”: 0.3,
      “session_level”: 150,
     “session_level_direction”: “up”
    }
 
 
 
 
 
 
………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………………
 
 
 
 
7. END SESSION (when session is complete)
 
 
 
A. Calculate the “session score":
 
 
    - The session score must be an integer number from 0 to 100
    - we simply do the SUM(all interactions’ rate) / Session nbr interaction 
        - then we rounded the result to 0
 
 
 
 
B. Calculate the “session boredom”:
 
 
 
    - The session boredom rate must be a decimal number from 0 to 1
    - we simply do the SUM(all interactions’ boredom rate) / Session nbr interaction 
        - then we rounded the result to 2
    - Calculation:
        - SUM (all cycle boredom of the session) / nbr of cycle in the session = end session boredom rate (rounded to 2)
 
 
 
 
 
 
 
C. Calculate the “session user level”:
 
 
    - Every time the cycle ends, the session level needs to be reset. (The session level + the not rounded cycle level) / 2
    - for example:
        - (150 + 114) / 2 = 132
        - 132 is closer to 150, so the reset session level is still 150
 
 
 
 
 
D. Calculate the “session level direction”:
 
 
    - Every time the cycle ends, the session level direction needs to be reset. Check the difference between the not rounded new session level and the previous session level
        - 132 is lower than 150 so the session level direction is “down”
        - if the not rounded new session level was 162, so it will be “up”
        - however, if the new session level was between 140 and 160 it will be “stable”. To be stable we need to have only 10 points difference from the previous session level.
 
 
 
 
 
E. Update the user session “notions rate” 
 
when the user level goes up (if necessary)
 
 
    - The user level will necessarily goes up overtime. When a user level goes up (it can happen at the end of a cycle or at the end of a session), in such case, the app needs to check if some notions level owned are reached.
 
    - A notion is considered fully owned when the user level is equal or higher than the notion Level owned. When it happens we need to update the notion rate to 1 in the latest record in session_notion
 
    - For example, at the beginning of a session the user level is 100. However at the end of the session the user level goes up to 150. And a notion level owned was cap to 150. In such case, the notion’s notion rate must be updated to 1.
 
 
 
 
when the user level goes down (if necessary)
 
 
    - The user level can sometimes goes down. When a user level goes down (it can happen at the end of a cycle or at the end of a session), in such case, the app needs to check if some notions level owned are crossed.
 
    - A notion is considered unowned when it has a notion rate of 1, but the user level calculated is now lower than the notion level owned. When it happens, the notion’s notion rate must be updated to 0.99
 
    - For example, at the beginning of a session the user level is 150. However at the end of the session the user level goes down to 100. And a notion level owned was cap to 150. In such case, the notion’s notion rate must be updated to 0.99
 
 
 
 
 
G. Save data in database:
 
 
 
    {
      “user_id”: “USER202505099999”,
      “user_level”: 150,
         “session_id”: “SESSION202505090895",
      “session_status”: “complete”,
      “session_score”: 72,
      “session_level”: 150,
      “session_level_direction”: “up”,
      “session_mood”: “effective”,
      “session_repetition”: “high”,
      “session_boredom”: 0.4
    }
 
