import sys
sys.path.append('/home/rtucker/comment_model_support')

from syc_import import reformat_wikitext, render_wikitext, isolate_comments
from django.contrib.auth.models import User

content = """[[Image(DQBlizzard.png,right,thumbnail,300,noborder,"Blizzard Example, Web Screenshot")]]

||<class="tablehead">'''Location'''||
||[[Address("1100 ["Jefferson Road"], Rochester, NY 14623")]]||
||<class="tablehead">'''Hours''' (as of July 2012)||
||["Info Needed"]||
||<class="tablehead">'''Phone'''||
||585 475 1141||
||<class="tablehead">'''Wheelchair Accessible'''||
||Yes||
||<class="tablehead">'''Alcohol'''||
||No||
##||<class="tablehead">'''Email'''||
##||[[MailTo(info AT domain DOT com)]]||
||<class="tablehead">'''Website'''||
||http://DQRochester.com||
||[http://www.facebook.com/DqRochester Facebook]||

'''Dairy Queen''' is a ["chain restaurants" national chain] ["ice cream"] parlor and restaurant. The Dairy Queen Grill & Chill on Jefferson Road, near ["Henrietta Plaza"] is currently its only location in the Rochester region. The [http://www.dairyqueen.com/us-en/store-details/1700/ next closest] DQ is in the Village of [wiki:BufWiki:Village_of_Williamsville Williamsville], near ["Buffalo"].

It had its grand opening on August 6, ["2012/Openings" 2012] and broke the U.S. franchise record for best opening day [[FootNote(http://www.democratandchronicle.com/article/20120807/LIVING/120807001/Dairy-Queen-opening-brings-crowd-Henrietta)]].

[[Comments]]
------
''2009-03-31 12:45:35'' [[nbsp]] Is the ACT program related to CODIP? (http://www.childrensinstitute.net/programs/CODIP/) They seem to be very similar.

Also, the website linked to on the ACT Program page doesn't even mention the ACT program or "For the children". You have to mouseover the "Lists by Region:" navigation item, download the "Finger Lakes" pdf, and the website listed in that PDF doesn't even exist anymore, but it was on that site that I found the CODIP program. --["Users/AlexanderGartley"]
------
''2009-03-31 13:50:16'' [[nbsp]] I added the link to the resources pages. I did quite a bit of search drill down trying to find specific websites/pages to link to, but without any specific hits other than ones I put in the Notes and References list. --["Users/BradMandell"]
------
''2009-03-31 13:57:22'' [[nbsp]] Based on my reading, the CODIP is a school based program. There were some archaic search results to the childrensinstitute where they were working with the ACT program. It appears that the ACT Program is the only one certified to meet the specific goals by the NY courts. I had planned to integrate some 7th Judicial Court material (some info already in ["Rochester City Court"], but got waylaid on other tasks. --["Users/BradMandell"]
------
''2010-04-16 17:42:04'' [[nbsp]] Long time fan of DQ - the Blizzards are great, my favorites include the Butterfinger Blizzard and the Cappuccino-Heath Blizzard. Hoping an investor takes note (:>) --["Users/BradMandell"]
------
''2012-01-06 16:37:14'' [[nbsp]] I am so excited that a DQ is coming to Rochester! I'm hoping they open in 2012. --["Users/AlexanderGartley"]
------
''2012-08-01 16:41:29'' [[nbsp]] going to get a blizzard when it opens up --["Users/bonnev659"]
------
''2012-08-01 17:24:17'' [[nbsp]] Wow, I can't believe people are getting so excited about a national chain that serves artificially flavored and colored custard! I mean, Mc D's serves custard that's about the same, and their burgers aren't nearly as greasy! --["Users/alex-c"]
------
''2012-08-01 17:34:49'' [[nbsp]] Please stop being so friggin negative Alex-C. Alexander and Bonne---I'm with you. Pleased we're getting one. I would suggest waiting and trying it before judging it.  --["Users/peteb"]
------
''2012-08-01 18:11:27'' [[nbsp]] I agree with Alex.  --["Users/EileenF"]
------
''2012-08-01 21:28:04'' [[nbsp]] FWIW, I've been to DOZENS of DQ's in the midwest, south, and west coast. In most small towns, you either have a Sonic or a DQ (maybe a Rax) as the "2nd tier fast food place", usually down the road from the McD's or the Shoney's. In most of the Midwest, they are in the rear of a large gas-station/convenience store/fast food joint. There ain't NOTHIN' special about DQ, aside from their huge advertising budget. Just another place for people to stuff their faces with too much fat and sugar. --["Users/alex-c"]
------
''2012-08-03 19:33:34'' [[nbsp]] OK, for all you people who just can't wait, it's open. So, somebody needs to go over there, sample their predictable wares, post a lackluster reviews so that Eileen and I can say "we TOLD you so". Please, somebody? --["Users/alex-c"]
------
''2012-08-07 12:30:26'' [[nbsp]] I've been to many DQ's and I enjoy the ice cream, it's ice cream not custard and really like the chocolate shell and sundaes.  No need to fight people.  Sure it's loaded with fat, sugar grease what have you but so is the beloved Garbage Plate and Abbott's.  Not like we are eating this stuff every day. Enjoy everyone!     --["Users/NewtonNola"]
------
''2012-09-07 11:24:52'' [[nbsp]] Here's a novel idea for people like alex-c: refrain from commenting on a location unless you've ACTUALLY BEEN THERE.  An informed opinion is certainly more constructive than an unbased one. --["Users/mbetush"]
------
''2012-09-07 12:09:54'' [[nbsp]] I agree, another novel idea is ignore his reviews because they seem to all be negative, I'm not crazy about chain restaurants either but I'm not above hitting one up for a quick bite, even if it's not locally-sourced or organic. Sometimes, I need the grease. --["Users/PDub"]
"""

content = reformat_wikitext(content)
html = render_wikitext(content, page_slug="Dairy_Queen", isolating_comments=True)
text, label, comments = isolate_comments(html)

print "TEXT:", text
print ""
print "Label:", label
print ""
for dttm, userslug, content in comments:
    username = userslug.split('/')[1]
    print username
    print "COMMENT:", dttm, User.objects.get(username__iexact=username), content


