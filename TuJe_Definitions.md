Definitions:
 
 
- user id = a unique and custom id defines when the user create his account.
 
- user level = during every session the app will calculate the user level. In order to make it easier, the level will be in number. The European language level system goes from A0 to C1 which correspond in TuJe app from 0 to 500 and it goes by 50.
    - A0.0    = 0
    - A0.1    = 50
    - A1.0    = 100
    - A1.1    = 150
    - A2.0    = 200
    - A2.1    = 250
    - B1.0    = 300
    - B1.1    = 350
    - B2.0    = 400
    - B2.1    = 450
    - C1.0    = 500
 
- user goal = this is an information that the user is setting when he created his account. The user goal is the main reason why the user wants to learn to speak French. In the app the user goals are displayed with words but this text could change in the future, so to avoid any issue, each user goal options will match a number code that will stay the same.
    - love the language        = 1
    - personal interest        = 2
    - travel and vacation        = 3
    - partner and family        = 4
    - work and carrier        = 5
    - exam & certification    = 6
 
- user interest = this is a list of topics the user might be mostly interested in. In database there will be a table called “brain_interest”.  There are different ways to set this list, like when the user create his TuJe account and select his user goal, that goal will auto-select some interests, then user can uncheck some or check other interest. Second important way to adjust this list of interest is during all sessions the user will do. Indeed, if an interaction asks something like “do you like to do yoga?” And the user is answering yes, it might add yoga as an interest for the user. But this process will be define precisely later.
 
- session = it’s technically the class that the user will start every time is wants to use the app TuJe. A session is structured with cycles.
 
- session id = every time a user starts a new session, a new unique and custom id is generated.
 
- session rank = every time a user starts a new session, it needs to be ranked according any others sessions that have ever been created by the same user.     - It’s like SUM(all sessions) + 1 = rank
        - For example: 8 sessions done + 1 = 9
 
- session score = it’s a integer number from 0 to 100. It’s the overall score of the session after the user as completed all interactions and cycles.
 
- session level = it’s an integer number from 0 to 500 and it goes per 50. The session level will be calculated at the very beginning of the session and at the end.
 
- Session Level Direction = it gives an idea if the “session level” is currently going up, down or stable comparing with the user level set at the beginning of the session. There are three level direction:
    - up
    - stable
    - down 
 
- session status = a status to know how the session is or was conducted
    - active = user started a session and still working on it (less than 60 mins of inactivity)
    - complete = user finished the session, whatever the score is.
    - incomplete = user abandoned the session in middle, after 60 mins of inactivity
 
- session mood = for every session started, the app will show different options on how the user wants the session approach would be. The app will suggest what mood is recommended. But the user is free to choose among:
        - Effective = this mood is for user who wants to focus on learning French seriously in an effective way
        - Playful = this mood is for user who wants to play more than learning
        - Cultural = this mood is for user who wants to learn French with cultural topics
        - Relax = this mood is for user who wants to go easy peasy, no pressure
        - Listening = this mood is for user who wants to practice listening, no speaking
 
- session mood recommendation = this is something that will be used only when the user will begin a new session and before starting it, the user will choose the session mood. So the app will have to recommend what session mood should be. But the user will be free to choose whatever he wants.
 
- session nbr of cycle = it’s a number of cycles that the user will choose when he will select how long he would like to be the session. The user could select this information at every beginning of every session, or set it as a setting so the app will always begins a session with the same number of cycles.
        - 3 cycles if user selects = 10-15 mins session
        - 5 cycles if user selects = 30-35 mins session
        - 7 cycles if user selects = 45-50 mins session
 
- session nbr of interaction = it’s a number of total interaction in the session. Considering that every cycles can only contain 7 interactions maximum, the number of total interaction can only be:
        - 3 cycles = 21 interactions
        - 5 cycles = 35 interactions
        - 7 cycles = 49 interactions
 
- top session mood = it’s the session mood that was the top one used for the last 5 sessions
 
- top session mood rate = it’s a number, decimal or integer, which is the rate of the top session mood used for the last 5 sessions
 
- streak30 = the rate of session complete by the user in the last 30 days. 
        - for example if the user did 25 sessions in the last 30 days = 0.83 (rounded to 2)
 
- streak7 = the rate of session complete by the user in the last 7 days. 
        - for example if the user did 4 sessions in the last 7 days = 0.57 (rounded to 2)
 
- notions = are all concept knowledges that a user needs to master in order to speak and comprehend French language. They are concepts. It’s not like vocabulary, it’s more like grammar and some key words or expressions, conjugations and tips for listening and speaking. Notions are saved in the database table called brain_notion. Notions are classified in the database table called brain_notion from their level. The same level system as the user level, from 0 to 500 and it goes per 50. So Notions are the back bone of the French app to know what to learn, to practice and to review before to move on.
 
- session_notion = when a user uses the app, he will necessarily be exposed to some notions in order to learn French. To track how much the user grasped each notions displayed, there will be another table in database called “session_notion” with this structure below. Session_notion records will be often updated during a session. First while setting the session at the very beginning even before starting the first cycle. Then along the session after completing each interaction. And finally at the end of the session to give to the user a proper feedback.
 
- notion rate = it’s a decimal number from 0 to 1. 1 means that the user know perfectly the notion. For a notion to be grasped by a user, the user must understand the notion in passive and active way. Passive is like listening the notion in an interaction, and active it’s when a user uses the notion when he is answering. Initially a new notion introduced to the user will have a notion rate by default is 0.
 
- notion introduction date = it is the timestamp when a notion is introduced to a user
 
- notion weightiness = is a decimal number from 0 to 1. 1 means the importance of the notion is at the maximum. This data is interesting when the app has to prioritize notions to use during cycles. It’s also a data that will influence how the app will calculate the notion rate.
 
- notion level from = from what level (0 to 500) the app can start introducing a notion.
 
- notion level owned = up to what level (0 to 500) a notion will be considered fully grasped.
 
- notion passive mentioned = it’s an integer number of how many times the notion will be mentioned by the app passively (in interaction). This number is founded in database table session_notion
 
- notion active mentioned = it’s an integer number of how many times the notion will be mentioned by the user actively (in user answers). This number is founded in database table session_notion
 
- notion passive rate = it’s a decimal number of how many times the notion will be mentioned by the app passively among all notions mentioned in the last 7 days. Notion passive rate = (nbr of passive mentions of the notion / nbr of passive mentions of all notions) in all session in the last 7 days
 
- notion active rate = it’s a decimal number of how many times the notion will be mention by the app actively among all notions mentioned in the last 7 days. Notion active rate = (nbr of active mentions of the notion / nbr of active mentions of all notions) in all session in the last 7 days
 
- The list of notions = it’s a list of all notions that the user is currently working on. Notions with a notion rate of 0 or 1 are excluded. This list is defined before every new cycle.
 
- notion priority rate =     it is a decimal number from 0 to 1. 1 means that the notion is the top priority. This number must be defined before defining the list of notions before every new cycle.
 
- notion complexity rate = it is a decimal number from 0 to 1. 1 means that the notion is very hard to learn for a user. This number must be defined before defining the list of notions before every new cycle.
 
- session boredom = it’s completely normal when someone learns a language to feel boredom. Indeed, learning a language is often a journey of years. Sometimes we start motivated and then it’s faded. TuJe app needs to recognize early signs of boredom in order to adjust the service and try to keep users motivated. it’s a decimal number from 0 to 1. 1 means that the user has a important boredom while using the app.
 
- cycle boredom = it’s a decimal number from 0 to 1. 1 means the user has a huge boredom during the cycle
 
- interaction boredom = it’s a decimal number from 0 to 1. 1 means the user has a huge boredom during the interaction
 
- content is “seen” or “new” = it’s subtopics, interactions, or intents can be considered “seen” if it has been used in a session in a certain amount of days. If more the content is considered “new”:
    - A subtopic is considered “new” when it’s been 7 days or 5 sessions that it has not been displayed
    - An interaction is considered “new” when it’s been 4 days or 3 sessions that it has not been displayed
    - An intent is considered “new” when it’s been 4 days or 3 sessions that it has not been displayed
    - Otherwise, content are considered “seen” 
 
- combinations of repetition = learning a language and preserve the user motivation is a subtle job between introducing something new and reusing a content that is already seen. In order to manage this situation I designed some combinations of level of repetition. A combination is a pattern of a subtopic with an interaction, an interaction transcription and the intent. Each elements can be new or already seen. Depending of the pattern more new or more seen there is a level of boredom. To make it easy to understand, more the boredom is high, more the combination will have content new. 
    - There are only 5 combinations:
        - Combination 1 = boredom 0, subtopic “seen”, interaction transcription “seen”, interaction intent “seen”
        - Combination 2 = boredom 0.1, subtopic “seen”, interaction transcription “new”, interaction intent “seen”
        - Combination 3 = boredom 0.3, subtopic “seen”, interaction transcription “new”, interaction intent “new”
        - Combination 4 = boredom 0.4, subtopic “new”, interaction transcription “seen”, interaction intent “seen”
        - Combination 5 = boredom 0.5, subtopic “new”, interaction transcription “new”, interaction intent “new”
    - For example, if we check the combination 1, we see that all content are marked “seen”, which means that if the app must use this combination, it will have to find interactions that are completely “seen”, the exact same interaction id. However, for the combination 4, the transcription is “seen” and the intent of the interaction too, but not the subtopic, which means that it’s an interaction from another subtopic but with the exact same transcription like another interaction. 
    - The boredom is key here to define from which level of combination the app will look for interactions during a cycle. If a user has 0 boredom, the app can look for interaction from the combination 1 up to 5. However, if the boredom is at 0.46, the app will look for interactions from the combination 4 and also in 5.
 
- intent = it’s the main idea of what is the meaning of an interaction. Intents helps to figured what kind of vocabulary the user might need to use depending of the interaction. 
 
- list of intents already seen = it’s a list of all intents that was displayed to the user in all sessions in the last 7 days in all cycles from cycle goal “story” and “intent”
 
- list of subtopics already seen = it’s a list of all subtopics that was displayed to the user in all sessions in the last 7 days in all cycles from cycle goal “story” and “intent”
 
- cycle id = every time a new cycle is created a new unique and custom id is generated.
 
- cycle rank = every time a new cycle is created, it needs to be ranked according any others cycles that have been created in the same session. It’s pretty much SUM(all completed cycle of the session) + 1 = new cycle rank
 
- cycle level = it’s a number (from 0 to 500) like user level. The Cycle Level is defined before the cycle starts. It helps to know at what level interactions must be.
 
- cycle level direction = it gives an idea if the level of the cycle on going is currently going up, down or stable comparing with the cycle level set at the beginning of the cycle. There are three level direction:
    - up
    - stable
    - down 
 
- cycle user level = it’s a number (from 0 to 500) like user level. It’s like the Cycle Level but it’s defined at the end of the cycle, when it’s completed. It helps to know at what level the user handle the overall cycle.
 
- cycle status = a status to know how the cycle is or was conducted
    - active = user is currently working in the cycle into an active session
    - complete = user finished the cycle, whatever the score is.
    - incomplete = user abandoned the session in middle, after 60 mins of inactivity the session is marked incomplete and so the active cycle
 
- cycle goal = there are 3 main goals a cycle can focus on, in order to help the user to reach a certain target:
    - Goal “notion”, it’s the idea to focus on the top notions of the list of session notion, so the subtopic and the logic of the conversation is not important. For this goal, the user can answer different interactions from different subtopics and different intents.
    - Goal “intent”, it’s the idea to focus on the comprehension of the interaction intent, the meaning, which is the vocabulary. For this goal, it’s important to work around the same vocabulary. We might continue the cycle on the same subtopic but it could be necessary to use a similar subtopics 
    - Goal “story”, it’s the idea to continue a conversation or a game logically whatever the notions or the vocabulary is displayed. It’s more like a pure practice of the language.
 
- change cycle goal = when the app will introduce to the user the new cycle that he will work on, the cycle will be set with a cycle goal. The user might want to change the goal for another one. It will be always possible but it can show something about the user motivation so the boredom.
 
- change cycle subtopic = changing the subtopic before starting a cycle can only be done by a user, if the cycle goal is “story”. The user might want to change the subtopic for another one. It will be always possible only at the beginning of the cycle, but it can show something about the user boredom.
 
- subtopic = it’s basically the topic where come from several interactions. In the app, I call topics = subtopics, because I wish to group subtopics into topics later for UX idea. For example, yoga, football, tennis are subtopics of a topic calls sport. Every interactions are part of a single subtopic.
 
- subtopic level from = it’s the level (from 0 to 500) that the subtopic is available for a user. It’s helpful to know if a subtopic is good for a certain user level.
 
- interaction = it’s basically an exercise. An interaction is made of a single short vertical video. Then the user has to answer to the video for whatever it is asked for.
 
- interaction score = previously called “interaction rate”, it’s the score that is given to an unique interaction after the user has interacted with it (listened it and then answered it). The interaction score ranges between 0 to 100. If it’s 0, it means the interaction has been handle poorly. But if it’s 100 it means the interaction has been handle perfectly. It must be calculated every time the user answers. Even if there are several answers per interaction.
 
- gross interaction score = it’s a number. In order to calculate the interaction score, we need to get the gross interaction score.
 
- gross score = It’s a number. In order to calculate the gross interaction score, we need to get the gross score.
 
- Interaction Optimum Level = it’s a number that can be found in the database “brain_interaction’s interaction_optimum_level” after the matching answer process has returned a valid match from “brain_interaction_answer”. This number means at what level the user must be to get the best score which is 100. If the user level is higher than the interaction optimum level, it would mean that the interaction can be considered a little bit easy for the user, so the interaction score could be calculated harder depending of the answer.
 
- Answer Optimum Level = it’s a number that can be found in the database “brain_answer’s answer_optimum_level” after the matching answer process has returned a valid match from “brain_interaction_answer”. This number means at what level the user must be to get the best score which is 100. If the user level is higher than the answer optimum level, it would mean that the answer can be considered a little bit easy for the user, so the interaction score could be lower even if the answer was right, but too easy.
 
- Bonus / Malus = in the database there is the “brain_bonus_malus”. Bonus are positive point to give to the user, so it can increase the interaction score. Whereas malus are negative, so it can decrease the interaction score. The value of bonus and malus is in the database. The way to give a bonus or a malus to a interaction will be defined in the future. 
 
- modulo = it is a number from 0 to 1. This number is used to minus the impact of the malus only. It’s like a coefficient that we multiply to the sum of malus value in order to ease it. If 0 it will suppress the malus whereas if it’s 1, the sum of the malus will be entire. But if it’s a decimal number, it will more or less decrease the malus total value.
 
- interaction user level = it’s a number (from 0 to 500) that is designed to know at which level the user is handling an interaction. This number is recalculated every time a user complete an interaction.
 
- interaction level from = it’s a number (from 0 to 500) and it represents at what minimum level an interaction can be displayed to a user.
 
- interaction type = there are many types of interactions in the app TuJe. Each type require the user to do something different:
    - Conversation =     this is the classic video interaction with a question asked to the user and answer by speaking
    - True / False =     user listen to a statement in French and he needs to press buttons if it’s true or false
    - Seek and Find = the user watch an image and he has to give info to tell where is the thing located on the image
    - First-person =    the user watch video at the first-person and user has to give commands and orders to do a task so it will progress into the game
    - Quiz =     general questions are asked to the user and he has to answer by pressing buttons
    - Ask questions =     let user ask questions in order for him to be in control of the conversation
    - Describe =    show to user a picture, and let him describe it
    - On the phone =    no more image or videos, like a conversation on the phone or on a blind zoom call with friends or a service
    - Listen and Touch =    user watch and listen to a longer video and he has to press a button to show that he understood what the video is saying
    - Pet a pet = facing a cat or a dog and try to talk to him
    - Third-person =    user is watching videos with a conversation between two people and he has to press a button to show that he understood
    - Guess what = user watch a video with info about someone or something and user must guess what it’s about by pressing the button
    - Make a wish = show user a non verbal situation, and let user expressing what he wants, or give an order
    - Find the suspect =    Listening exercise where the user get info about an event, people, situation and must find the suspect
    - Long talk = let the user speak in French by making several sentences about a open conversation topic
    - Repeat = make user repeat as good as possible what he is listening.
 
- the list of interactions = at the beginning a every cycle the app needs to perform some searches to find the best interactions to display to the user during the cycle. The idea is to have a list of interactions where the app will easily pick to continue the cycle without triggering a complete search everytime. This list of interactions can be tens interactions even if a cycle only needs 7 interactions.
 
- interaction entry point = when a new cycle has a cycle goal “story” the first interaction of the cycle must be an entry point. Which means that the interaction can set a context to start a conversation or a game. This info will be available in brain_interaction.
 
- nbr of attempts = it’s an integer number that represents the number of attempts the user did to answer a single interaction
 
- nbr of listenings = it’s an integer number that represents the number of listenings the user did when he plays the interaction
 
- speaking rate = it’s a decimal number from 0 to 1. 1 means the user is trying his best to speak in French. Speaking rate is only calculated at the end of an interaction complete. Because TuJe app is designed to help users to learn and speak French, knowing if a user is trying to speak as much as possible is important. Some interaction types require less or even no speaking. In such case the app won’t calculate the speaking rate.
 
- speaking optimum level = it’s a number look like the user level from 0 to 500 and it goes per 50. It can be found in the database table brain_interaction_answer. It works the same as the interaction optimum level or the answer optimum level. It says at what level the answer can provide the best speaking rate for a user. If the user level is higher than the speaking optimum level, it would mean that the answer was to easy.
 
- nbr of hint = hints are like small help that user can get in order to understand of answer an interaction. Every time a user press the button hint and check the hint provided, it will increment for a specific interaction the number of hints used. it’s an integer number that represent the number of hints the user needed. On screen, it will be represented by a button. If the user press it, it will provide a little help to the user to understand the interaction or guess a good answer. It is represented by a button that is specifically activated at a certain point during an interaction. More the user will press the button, more the hint will provide a deeper help to understand and answer the interaction. This is how the hint integer number will be incremented from 0 and it increments each time the user press the button hint to get a better hint each time. There is a brain_hint table in database that will be connected to the brain-interaction table. There are different hint types:
    - Hint 1: give a brief idea of the meaning of the interaction with an icon puzzle
    - Hint 2: show a gif, non-verbal info, like using gesture, facial expression, or object
    - Hint 3: give an idea in english
    - Hint 4: give a small part of a potential answer
    - Hint 5: says an almost full answer in a video with a missing part that the user will need to find out
 
- help rate = help is a button that user can press to get help to understand or answer an interaction. Depending how much the user will get help, if he needs a little or a complete help to figured the interaction and an answer, it will define a help rate for a specific interaction. it’s a decimal number from 0 to 1. 1 means the user needs a lot of help. Help is different from hint. When the user will press it, the user will be able to choose in the submenu what help does he need like “help to understand” or ”help to answer”.
    - Help for understanding the interaction:
        - User could get a slower version of the video interaction, something more articulated to help distinguishing words
        - User could check some specific parts of the interaction to figure individually what it means
        - User could finally get the complete translation of the interaction in English
    - Help to answer the interaction:
        - User could get access to some vocabulary
        - User could get tips of what words or group of words to reuse in a good answer
        - User could get a list of potential good answers
